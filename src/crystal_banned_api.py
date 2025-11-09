"""
Pylint plugin to ban specific API patterns in Crystal.
"""

import astroid
from pylint.checkers import BaseChecker


class CrystalBannedApiChecker(BaseChecker):
    """Checker to detect usage of banned API patterns."""
    
    name = 'crystal-banned-api'
    
    # Types of messages/diagnostics this plugin can emit. Each message type has:
    # - a short error code (ex: 'C9001')
    # - an error message that is printed when the message diagnostic is emitted
    #   (ex: 'Don't construct threads directly; ...')
    # - a long error code (ex: 'no-direct-thread')
    # - a help string, used in `pylint --list-msgs`
    #   (ex: 'Direct Thread(...) construction is not allowed. ...')
    # 
    # NOTE: Any new C9xxx codes added here should also be added to
    #       "enable" key in .pylintrc.
    msgs = {
        'C9001': (
            "Don't construct threads directly; use bg_call_later() from crystal.util.xthreading instead",
            'no-direct-thread',
            "Direct Thread(...) construction is not allowed. Use bg_call_later() instead.",
        ),
        'C9002': (
            "Don't call wx.Dialog.ShowModal() directly; use ShowModal() from crystal.util.wx_dialog instead",
            'no-direct-showmodal',
            "Direct ShowModal() call on dialog is not allowed. Use ShowModal() from crystal.util.wx_dialog instead.",
        ),
        'C9003': (
            "Don't call wx.Dialog.ShowWindowModal() directly; use ShowWindowModal() from crystal.util.wx_dialog instead",
            'no-direct-showwindowmodal',
            "Direct ShowWindowModal() call on dialog is not allowed. Use ShowWindowModal() from crystal.util.wx_dialog instead.",
        ),
        'C9004': (
            "Don't call wx.SystemSettings.GetAppearance().IsDark() directly; use IsDark() from crystal.util.wx_system_appearance instead",
            'no-direct-isdark',
            "Direct IsDark() call is not allowed. Use IsDark() from crystal.util.wx_system_appearance instead.",
        ),
        'C9005': (
            "Don't call wx.Window.Bind() directly; use bind() from crystal.util.wx_bind instead",
            'no-direct-bind',
            "Direct Bind() call is not allowed. Use bind() from crystal.util.wx_bind instead.",
        ),
        'C9006': (
            "Don't call wx.Window.SetFocus() directly; use SetFocus() from crystal.util.wx_window instead",
            'no-direct-setfocus',
            "Direct SetFocus() call is not allowed. Use SetFocus() from crystal.util.wx_window instead.",
        ),
    }
    
    def visit_call(self, node: astroid.Call) -> None:
        """Check for banned API patterns in function calls."""
        
        # Thread(...), threading.Thread(...)
        if self._is_thread_call(node):
            self.add_message('no-direct-thread', node=node)
        
        # dialog.ShowModal(...)
        if self._is_dialog_showmodal_call(node):
            self.add_message('no-direct-showmodal', node=node)
        
        # dialog.ShowWindowModal(...)
        if self._is_dialog_showwindowmodal_call(node):
            self.add_message('no-direct-showwindowmodal', node=node)
        
        # wx.SystemSettings.GetAppearance().IsDark(...)
        if self._is_appearance_isdark_call(node):
            self.add_message('no-direct-isdark', node=node)
        
        # window.Bind(...)
        if self._is_window_bind_call(node):
            self.add_message('no-direct-bind', node=node)
        
        # window.SetFocus(...)
        if self._is_window_setfocus_call(node):
            self.add_message('no-direct-setfocus', node=node)
    
    def _is_thread_call(self, node: astroid.Call) -> bool:
        # Thread(...)
        if isinstance(node.func, astroid.Name) and node.func.name == 'Thread':
            return True
        
        # threading.Thread(...)
        if isinstance(node.func, astroid.Attribute):
            if node.func.attrname == 'Thread':
                if isinstance(node.func.expr, astroid.Name):
                    if node.func.expr.name == 'threading':
                        return True
        
        return False
    
    def _is_dialog_showmodal_call(self, node: astroid.Call) -> bool:
        # dialog.ShowModal(...)
        if isinstance(node.func, astroid.Attribute):
            if node.func.attrname == 'ShowModal':
                # This is a call to ShowModal() method on some object,
                # presumably a wx.Dialog. Ban it.
                return True
        
        return False
    
    def _is_dialog_showwindowmodal_call(self, node: astroid.Call) -> bool:
        # dialog.ShowWindowModal(...)
        if isinstance(node.func, astroid.Attribute):
            if node.func.attrname == 'ShowWindowModal':
                # This is a call to ShowWindowModal() method on some object,
                # presumably a wx.Dialog. Ban it.
                return True
        
        return False
    
    def _is_appearance_isdark_call(self, node: astroid.Call) -> bool:
        # wx.SystemSettings.GetAppearance().IsDark(...)
        if isinstance(node.func, astroid.Attribute):
            if node.func.attrname == 'IsDark':
                # This is a call to IsDark() method on some object,
                # presumably wx.SystemSettings.GetAppearance(). Ban it.
                return True
        
        return False
    
    def _is_window_bind_call(self, node: astroid.Call) -> bool:
        # window.Bind(...)
        if isinstance(node.func, astroid.Attribute):
            if node.func.attrname == 'Bind':
                # This is a call to Bind() method on some object,
                # presumably a wx.Window. Ban it.
                return True
        
        return False
    
    def _is_window_setfocus_call(self, node: astroid.Call) -> bool:
        # window.SetFocus(...)
        if isinstance(node.func, astroid.Attribute):
            if node.func.attrname == 'SetFocus':
                # This is a call to SetFocus() method on some object,
                # presumably a wx.Window. Ban it.
                return True
        
        return False


def register(linter):
    """Register the checker with pylint."""
    linter.register_checker(CrystalBannedApiChecker(linter))
