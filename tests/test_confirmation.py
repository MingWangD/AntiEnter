"""
T04 & T05: 确认识别分类器与误判防范测试
验证：
- 编辑区、正文、代码中的泛词（"你好"、"let skipped = true"、"Confirming migration"、"Skip tutorial"）零误判
- 否定词与取消按钮（"Do not proceed"、"Don't allow"、"Cancel"、"Deny"）绝不误判
- 高危熔断开启时，所有自动动作（通用词 "Confirm"/"Yes"/"Proceed" 及 "Submit ↵"）默认全面拦截
- 必须持有与当前请求工具绑定的、未消费的短期有效放行令牌才允许自动确认
- 令牌防重放：已消费 (consumed=True) 的令牌绝不重复授权
- 严格 Schema 校验：缺少 tool 字段、tool 为 null 或非字符串时绝不授权
- 工具名规范化：支持命名空间工具名规范化匹配 (如 default_api:run_command -> run_command)
- 缺失、过期、ask 或工具不匹配的 decision.json 绝不授权
- 高危熔断显式关闭后，允许已验证模板自动放行
- 隐藏与禁用控件自动忽略
"""
from __future__ import annotations
import json
import time
import tempfile
import unittest
from pathlib import Path
from typing import Optional


class MockElement:
    def __init__(self, role: str, text: str = "", enabled: bool = True, visible: bool = True, children=None):
        self.role = role
        self.text = text
        self.enabled = enabled
        self.visible = visible
        self.children = children or []


def evaluate_decision_token(
    decision_file_path: Path,
    expected_tool: Optional[str] = None,
    now: Optional[float] = None,
) -> tuple[bool, bool]:
    """
    跨平台评估 antienter_decision.json 状态
    返回: (is_pending_ask, has_active_allow_token)
    与 Swift App、Swift CLI daemon 及 Windows daemon 的判定逻辑保持严格一致。
    """
    if now is None:
        now = time.time()
    if not decision_file_path.exists():
        return False, False
    try:
        with open(decision_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return False, False

        dec = data.get("decision")
        ts = float(data.get("timestamp", 0))
        consumed = bool(data.get("consumed", False))

        if dec == "ask" and (now - ts) < 30.0:
            return True, False

        if dec == "allow" and not consumed and (now - ts) < 10.0:
            if expected_tool is None or not expected_tool.strip():
                return False, False

            # 必须存在合法字符串类型的工具名
            actual_tool = data.get("canonical_tool") or data.get("tool")
            if not isinstance(actual_tool, str) or not actual_tool.strip():
                return False, False

            norm_expected = expected_tool.split(":")[-1].strip().lower()
            norm_actual = actual_tool.split(":")[-1].strip().lower()
            if norm_actual == norm_expected:
                return False, True
    except Exception:
        pass
    return False, False


def classify_element(
    elem: MockElement,
    safety_fuse_enabled: bool = True,
    has_safe_token: bool = False,
    is_pending_ask: bool = False,
) -> bool:
    """与 Swift 及 Windows 守护进程一致的纯逻辑判定模型"""
    if is_pending_ask:
        return False

    excluded_roles = {
        "AXTextArea", "AXTextField", "AXStaticText", "AXScrollArea", "AXWebArea",
        "edit", "scintilla", "richedit"
    }
    actionable_roles = {
        "AXButton", "AXRadioButton", "AXCheckBox", "AXPopUpButton", "button"
    }

    negative_words = [
        "do not", "don't", "never", "cancel", "deny", "reject",
        "refuse", "disallow", "no, ", "取消", "拒绝", "不",
    ]

    safe_exact_words = {
        "confirm", "submit", "proceed", "ok", "yes",
        "确定", "继续", "好", "skip", "跳过"
    }
    tool_exact_words = {"allow", "允许"}
    tool_permission_phrases = [
        "yes, allow this time",
        "allow this time",
        "yes, and always allow",
        "always allow",
        "allow pushing",
        "allow searching",
        "allow running",
        "allow editing",
        "allow writing",
        "始终允许",
        "本次允许",
        "总是允许",
    ]

    if not elem.visible or not elem.enabled:
        return False

    if elem.role in actionable_roles:
        t = elem.text.strip().lower()
        if not t:
            return False

        # 1. 否定词排除（如 "Do not proceed", "Don't allow", "Cancel"）
        if any(nw in t for nw in negative_words):
            return False

        # 规则：
        # 熔断开启时：所有动作（包括 "Submit ↵" 与通用确认词）均必须持有有效放行令牌！
        # 熔断关闭时：允许 "Submit ↵"、所有通用词及工具授权短语
        if not safety_fuse_enabled:
            allowed_phrases = ["submit ↵"] + tool_permission_phrases
            allowed_words = safe_exact_words | tool_exact_words
        elif has_safe_token:
            allowed_phrases = ["submit ↵"]
            allowed_words = set(safe_exact_words)
        else:
            allowed_phrases = []
            allowed_words = set()

        # 2. 强特征短语匹配
        if any(sp in t for sp in allowed_phrases):
            return True

        # 3. 精确按钮词匹配
        if t in allowed_words:
            return True

    if elem.role in excluded_roles:
        return False

    for child in elem.children:
        if classify_element(
            child,
            safety_fuse_enabled=safety_fuse_enabled,
            has_safe_token=has_safe_token,
            is_pending_ask=is_pending_ask,
        ):
            return True

    return False


class TestConfirmationClassifier(unittest.TestCase):
    def test_t04_false_positives_eliminated(self):
        """T04: 普通编辑文本、代码、否定按钮与非确认按钮零自动动作"""
        # 1. 编辑区 Value: "你好"
        edit_hello = MockElement("AXTextArea", text="你好")
        self.assertFalse(classify_element(edit_hello), "'你好' 不得触发自动确认")

        # 2. 代码区 Value: "let skipped = true"
        code_skip = MockElement("AXTextArea", text="let skipped = true")
        self.assertFalse(classify_element(code_skip), "'let skipped = true' 不得触发自动确认")

        # 3. 静态说明文字 Description: "Confirming migration"
        static_confirm = MockElement("AXStaticText", text="Confirming migration")
        self.assertFalse(classify_element(static_confirm), "'Confirming migration' 文本不得触发自动确认")

        # 4. 普通非确认按钮: "Skip tutorial"
        btn_tutorial = MockElement("AXButton", text="Skip tutorial")
        self.assertFalse(classify_element(btn_tutorial), "'Skip tutorial' 按钮不得触发自动确认")

        # 5. 否定含义按钮（子串防误触测试）
        btn_dont_proceed = MockElement("AXButton", text="Do not proceed")
        self.assertFalse(classify_element(btn_dont_proceed), "'Do not proceed' 不得误判为 proceed")

        btn_dont_allow = MockElement("AXButton", text="Don't allow")
        self.assertFalse(classify_element(btn_dont_allow), "'Don't allow' 不得误判")

        btn_cancel = MockElement("AXButton", text="Cancel")
        self.assertFalse(classify_element(btn_cancel), "'Cancel' 按钮不得触发确认")

        btn_deny = MockElement("AXButton", text="Deny")
        self.assertFalse(classify_element(btn_deny), "'Deny' 按钮不得触发确认")

    def test_t05_valid_templates_matched(self):
        """T05: 确认模板识别与安全熔断联动"""
        # 1. 通用安全流转模板在持令牌时放行
        btn_submit_arrow = MockElement("AXButton", text="Submit ↵")
        self.assertTrue(classify_element(btn_submit_arrow, safety_fuse_enabled=True, has_safe_token=True), "持令牌时 'Submit ↵' 应当正常触发")

        # 2. 通用确认词在持有令牌时放行
        btn_confirm = MockElement("AXButton", text="Confirm")
        self.assertTrue(classify_element(btn_confirm, safety_fuse_enabled=True, has_safe_token=True), "持令牌时 'Confirm' 应当正常触发")

        btn_proceed = MockElement("AXButton", text="Proceed")
        self.assertTrue(classify_element(btn_proceed, safety_fuse_enabled=True, has_safe_token=True), "持令牌时 'Proceed' 应当正常触发")

        btn_skip = MockElement("AXButton", text="Skip")
        self.assertTrue(classify_element(btn_skip, safety_fuse_enabled=True, has_safe_token=True), "持令牌时 'Skip' 应当正常触发")

        btn_ok_cn = MockElement("AXButton", text="好")
        self.assertTrue(classify_element(btn_ok_cn, safety_fuse_enabled=True, has_safe_token=True), "持令牌时 '好' 应当正常触发")

        # 3. 工具权限授权按钮：熔断开启时拒绝 UI 自动点击（交由 Hook 协议层判定）
        btn_tool_allow = MockElement("AXButton", text="Yes, allow this time")
        self.assertFalse(classify_element(btn_tool_allow, safety_fuse_enabled=True, has_safe_token=True), "熔断开启时 UI Watcher 不得越俎代庖自动点击工具权限按钮")

        btn_cn_always = MockElement("AXButton", text="总是允许")
        self.assertFalse(classify_element(btn_cn_always, safety_fuse_enabled=True, has_safe_token=True), "熔断开启时 '总是允许' 不得自动点击")

        # 4. 工具权限授权按钮：熔断显式关闭时允许自动点击
        self.assertTrue(classify_element(btn_tool_allow, safety_fuse_enabled=False), "熔断关闭时允许工具授权模板自动点击")
        self.assertTrue(classify_element(btn_cn_always, safety_fuse_enabled=False), "熔断关闭时允许 '总是允许' 自动点击")

        # 5. 隐藏与禁用控件测试
        btn_disabled = MockElement("AXButton", text="Confirm", enabled=False)
        self.assertFalse(classify_element(btn_disabled, has_safe_token=True), "禁用的确认按钮不得触发")

        btn_invisible = MockElement("AXButton", text="Confirm", visible=False)
        self.assertFalse(classify_element(btn_invisible, has_safe_token=True), "隐藏的确认按钮不得触发")

    def test_high_risk_modal_bare_confirm_blocked_under_fuse(self):
        """复核要求：熔断开启且无有效令牌时，高危授权窗口孤立的 'Confirm' 按钮必须被拦截"""
        btn_confirm = MockElement("AXButton", text="Confirm")
        self.assertFalse(
            classify_element(btn_confirm, safety_fuse_enabled=True, has_safe_token=False),
            "无令牌时熔断开启下纯 'Confirm' 必须被拦截"
        )

    def test_high_risk_modal_bare_yes_blocked_under_fuse(self):
        """复核要求：熔断开启且无有效令牌时，高危授权窗口孤立的 'Yes' 按钮必须被拦截"""
        btn_yes = MockElement("AXButton", text="Yes")
        self.assertFalse(
            classify_element(btn_yes, safety_fuse_enabled=True, has_safe_token=False),
            "无令牌时熔断开启下纯 'Yes' 必须被拦截"
        )

    def test_high_risk_modal_bare_submit_arrow_blocked_under_fuse(self):
        """复核要求：熔断开启且无有效令牌时，孤立的 'Submit ↵' 绝不得无条件放行"""
        btn_submit = MockElement("AXButton", text="Submit ↵")
        self.assertFalse(
            classify_element(btn_submit, safety_fuse_enabled=True, has_safe_token=False),
            "无令牌时熔断开启下纯 'Submit ↵' 必须被拦截"
        )

    def test_submit_arrow_allowed_when_fuse_disabled(self):
        """显式关闭熔断时，'Submit ↵' 允许无需令牌放行"""
        btn_submit = MockElement("AXButton", text="Submit ↵")
        self.assertTrue(
            classify_element(btn_submit, safety_fuse_enabled=False, has_safe_token=False),
            "熔断显式关闭时 'Submit ↵' 应当正常触发"
        )

    def test_missing_decision_file_blocks_all_actions(self):
        """复核要求：缺少 decision.json 时，不产生放行令牌，泛化确认词与 Submit ↵ 全部拦截"""
        with tempfile.TemporaryDirectory() as td:
            missing_file = Path(td) / "non_existent_decision.json"
            is_ask, has_token = evaluate_decision_token(missing_file, expected_tool="run_command")
            self.assertFalse(is_ask)
            self.assertFalse(has_token)

            btn = MockElement("AXButton", text="Confirm")
            self.assertFalse(
                classify_element(btn, safety_fuse_enabled=True, has_safe_token=has_token, is_pending_ask=is_ask),
                "缺少决策文件时不得放行 Confirm"
            )
            btn_sub = MockElement("AXButton", text="Submit ↵")
            self.assertFalse(
                classify_element(btn_sub, safety_fuse_enabled=True, has_safe_token=has_token, is_pending_ask=is_ask),
                "缺少决策文件时不得放行 Submit ↵"
            )

    def test_expired_decision_token_blocks_all_actions(self):
        """复核要求：decision.json 令牌过期 (>10s) 时，判定无效，全部确认动作拦截"""
        with tempfile.TemporaryDirectory() as td:
            dec_file = Path(td) / "antienter_decision.json"
            now = 1000.0
            data = {"decision": "allow", "tool": "run_command", "timestamp": now - 15.0, "consumed": False}
            with open(dec_file, "w", encoding="utf-8") as f:
                json.dump(data, f)

            is_ask, has_token = evaluate_decision_token(dec_file, expected_tool="run_command", now=now)
            self.assertFalse(has_token, "过期令牌必须失效")

            btn = MockElement("AXButton", text="Proceed")
            self.assertFalse(
                classify_element(btn, safety_fuse_enabled=True, has_safe_token=has_token, is_pending_ask=is_ask),
                "过期令牌不得放行 Proceed"
            )

    def test_ask_decision_blocks_all_actions(self):
        """复核要求：decision.json 为 ask 决策 (30s 内) 时，判定 pending ask，全量拦截 UI 动作"""
        with tempfile.TemporaryDirectory() as td:
            dec_file = Path(td) / "antienter_decision.json"
            now = 1000.0
            data = {"decision": "ask", "tool": "run_command", "reason": "高危命令", "timestamp": now - 5.0}
            with open(dec_file, "w", encoding="utf-8") as f:
                json.dump(data, f)

            is_ask, has_token = evaluate_decision_token(dec_file, expected_tool="run_command", now=now)
            self.assertTrue(is_ask, "活跃 ask 决策必须识别为 pending ask")
            self.assertFalse(has_token, "ask 决策不得提供放行令牌")

            btn_submit = MockElement("AXButton", text="Submit ↵")
            self.assertFalse(
                classify_element(btn_submit, safety_fuse_enabled=True, has_safe_token=has_token, is_pending_ask=is_ask),
                "Hook 处于 ask 状态时必须全面禁止 UI 自动按键"
            )

    def test_mismatched_tool_decision_blocks_all_actions(self):
        """复核要求：decision.json 工具不匹配时，拒绝授权令牌"""
        with tempfile.TemporaryDirectory() as td:
            dec_file = Path(td) / "antienter_decision.json"
            now = 1000.0
            data = {"decision": "allow", "tool": "run_command", "timestamp": now - 2.0, "consumed": False}
            with open(dec_file, "w", encoding="utf-8") as f:
                json.dump(data, f)

            is_ask, has_token = evaluate_decision_token(dec_file, expected_tool="write_to_file", now=now)
            self.assertFalse(has_token, "工具不匹配时令牌不得生效")

            btn = MockElement("AXButton", text="Confirm")
            self.assertFalse(
                classify_element(btn, safety_fuse_enabled=True, has_safe_token=has_token, is_pending_ask=is_ask),
                "工具不匹配时不得放行 Confirm"
            )

    def test_consumed_token_blocked_against_replay(self):
        """复核要求：已经消费 (consumed=True) 的令牌不得重复重放"""
        with tempfile.TemporaryDirectory() as td:
            dec_file = Path(td) / "antienter_decision.json"
            now = 1000.0
            data = {
                "decision": "allow",
                "tool": "run_command",
                "timestamp": now - 2.0,
                "consumed": True,
                "consumed_at": now - 1.0,
            }
            with open(dec_file, "w", encoding="utf-8") as f:
                json.dump(data, f)

            is_ask, has_token = evaluate_decision_token(dec_file, expected_tool="run_command", now=now)
            self.assertFalse(has_token, "已消费的令牌绝不得重复生效")

            btn = MockElement("AXButton", text="Confirm")
            self.assertFalse(
                classify_element(btn, safety_fuse_enabled=True, has_safe_token=has_token, is_pending_ask=is_ask),
                "已消费令牌不得放行确认"
            )

    def test_missing_tool_field_rejected(self):
        """复核要求：缺少 tool 字段的令牌必须拒绝"""
        with tempfile.TemporaryDirectory() as td:
            dec_file = Path(td) / "antienter_decision.json"
            now = 1000.0
            data = {"decision": "allow", "timestamp": now - 2.0, "consumed": False}
            with open(dec_file, "w", encoding="utf-8") as f:
                json.dump(data, f)

            is_ask, has_token = evaluate_decision_token(dec_file, expected_tool="run_command", now=now)
            self.assertFalse(has_token, "缺少 tool 字段的令牌必须被拒绝")

    def test_null_tool_field_rejected(self):
        """复核要求：tool 为 null 的令牌必须拒绝"""
        with tempfile.TemporaryDirectory() as td:
            dec_file = Path(td) / "antienter_decision.json"
            now = 1000.0
            data = {"decision": "allow", "tool": None, "timestamp": now - 2.0, "consumed": False}
            with open(dec_file, "w", encoding="utf-8") as f:
                json.dump(data, f)

            is_ask, has_token = evaluate_decision_token(dec_file, expected_tool="run_command", now=now)
            self.assertFalse(has_token, "tool 为 null 的令牌必须被拒绝")

    def test_non_string_tool_field_rejected(self):
        """复核要求：tool 为非字符串 (如整数/字典) 的令牌必须拒绝"""
        with tempfile.TemporaryDirectory() as td:
            dec_file = Path(td) / "antienter_decision.json"
            now = 1000.0
            data = {"decision": "allow", "tool": 12345, "timestamp": now - 2.0, "consumed": False}
            with open(dec_file, "w", encoding="utf-8") as f:
                json.dump(data, f)

            is_ask, has_token = evaluate_decision_token(dec_file, expected_tool="run_command", now=now)
            self.assertFalse(has_token, "tool 为非字符串的令牌必须被拒绝")

    def test_namespace_tool_normalization(self):
        """复核要求：支持命名空间工具名规范化匹配 (如 default_api:run_command -> run_command)"""
        with tempfile.TemporaryDirectory() as td:
            dec_file = Path(td) / "antienter_decision.json"
            now = 1000.0
            data = {
                "decision": "allow",
                "raw_tool": "default_api:run_command",
                "canonical_tool": "run_command",
                "tool": "run_command",
                "timestamp": now - 2.0,
                "consumed": False,
            }
            with open(dec_file, "w", encoding="utf-8") as f:
                json.dump(data, f)

            # expected 为命名空间形式，令牌为规范化形式
            _, has_token1 = evaluate_decision_token(dec_file, expected_tool="default_api:run_command", now=now)
            self.assertTrue(has_token1, "命名空间形式 expected 应匹配规范化令牌")

            # expected 为规范化形式
            _, has_token2 = evaluate_decision_token(dec_file, expected_tool="run_command", now=now)
            self.assertTrue(has_token2, "规范化 expected 应匹配规范化令牌")

    def test_active_allow_token_authorizes_generic_words(self):
        """正向校验：有效的 allow 令牌成功授权通用确认词与 Submit ↵"""
        with tempfile.TemporaryDirectory() as td:
            dec_file = Path(td) / "antienter_decision.json"
            now = 1000.0
            data = {
                "decision": "allow",
                "raw_tool": "run_command",
                "canonical_tool": "run_command",
                "tool": "run_command",
                "timestamp": now - 2.0,
                "consumed": False,
            }
            with open(dec_file, "w", encoding="utf-8") as f:
                json.dump(data, f)

            is_ask, has_token = evaluate_decision_token(dec_file, expected_tool="run_command", now=now)
            self.assertTrue(has_token, "有效 allow 令牌必须成功生效")

            btn_yes = MockElement("AXButton", text="Yes")
            self.assertTrue(
                classify_element(btn_yes, safety_fuse_enabled=True, has_safe_token=has_token, is_pending_ask=is_ask),
                "持有有效令牌时允许自动确认 Yes"
            )

            btn_submit = MockElement("AXButton", text="Submit ↵")
            self.assertTrue(
                classify_element(btn_submit, safety_fuse_enabled=True, has_safe_token=has_token, is_pending_ask=is_ask),
                "持有有效令牌时允许自动确认 Submit ↵"
            )


if __name__ == "__main__":
    unittest.main()
