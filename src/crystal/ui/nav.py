"""
Provides a Python interface for easily navigating/viewing/controlling a
wxPython-based program.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
# TODO: Promote the TreeItem abstraction to the crystal.ui package,
#       outside of the crystal.tests.** namespace
from crystal.tests.util.controls import TreeItem
from typing import Type, assert_never, Generic, Iterable, assert_type, overload, TYPE_CHECKING, TypeVar
import wx


# ------------------------------------------------------------------------------
# Navigator

_P = TypeVar('_P')  # peer


class Navigator(Generic[_P], Sequence['Navigator[_P]']):  # abstract
    """
    Points to a peer. Shows the peer's tree of descendents when printed.
    
    When viewed as a Sequence, returns a Navigator to navigate to each of the
    peer's direct children. See __getitem__() documentation for all ways
    to navigate.
    """
    
    _peer: _P
    
    # === Formatting ===
    
    def __repr__(self) -> str:
        """
        Describes a CodeExpression to obtain this navigator's peer
        and describes all of the peer's visible descendents, including a
        CodeExpression to navigate to each descendent.
        """
        raise NotImplementedError()
    
    @classmethod
    def _describe_children(cls,
            parent: _P,
            path: str,
            ) -> list[str]:
        raise NotImplementedError()
    
    @classmethod
    def _describe(cls, peer: _P) -> str:
        raise NotImplementedError()
    
    # === Navigation ===
    
    @overload
    def __getitem__(self, index: int) -> Navigator[_P]: ...
    @overload
    def __getitem__(self, index: slice) -> NavigatorSlice[_P]: ...
    def __getitem__(self, index: int | slice):
        """
        - navigator[i], where i is an int, returns a navigator pointing to
          the i'th visible child of this navigator's peer.
        - navigator[i:j:k], where i:j:k is a slice, returns navigators
          corresponding to the associated children of this navigator's peer.
        """
        raise NotImplementedError()
    
    def __len__(self) -> int:
        """
        The number of visible children of this navigator's peer.
        """
        raise NotImplementedError()
    
    # === Properties ===
    
    _PEER_ACCESSOR: str  # abstract
    """Name of the shorthand property that returns this navigator's peer."""
    
    @property
    def Query(self) -> CodeExpression:
        """
        A code expression suitable for including in production code
        which returns this navigator's peer.
        """
        raise NotImplementedError()
    
    @property
    def Q(self) -> CodeExpression:
        """
        Shorthand property equivalent to .Query, for quick scripts.
        """
        return self.Query


# ------------------------------------------------------------------------------
# WindowNavigator

class WindowNavigator(Navigator[wx.Window]):
    """
    Points to a wx.Window. Shows the window's tree of descendents when printed.
    
    When viewed as a Sequence, returns a WindowNavigator to navigate to each of the
    window's direct children. See __getitem__() documentation for all ways
    to navigate.
    """
    
    _DEFAULT_NAME_FOR_WINDOW_TYPE_STR = {
        wx.Button: wx.ButtonNameStr.decode('ascii'),
        wx.Frame: wx.FrameNameStr.decode('ascii'),
        wx.Panel: wx.PanelNameStr.decode('ascii'),
        wx.ScrollBar: wx.ScrollBarNameStr.decode('ascii'),
        wx.SplitterWindow: 'splitterWindow',
        wx.StaticBox: wx.StaticBoxNameStr.decode('ascii'),
        wx.StaticText: wx.StaticTextNameStr.decode('ascii'),
    }  # type: dict[type, str]

    # Maps integers to the corresponding 'wx.ID_*' symbol name, if available
    _SYMBOL_NAME_FOR_WX_ID_VALUE = {
        getattr(wx, name): f'wx.{name}'
        for name in dir(wx)
        if name.startswith('ID_')
    }
    
    # === Init ===

    def __init__(self, window: wx.Window | None = None, path: str = 'T', query: str | None = None) -> None:
        """
        Creates a navigator. Most code will obtain a navigator by navigating
        from the top navigator `T` rather than creating one directly.
        """
        self._peer = window
        self._path = path
        if (window is not None and 
                window.Name and 
                window.Name != self._DEFAULT_NAME_FOR_WINDOW_TYPE_STR.get(type(window)) and
                wx.FindWindowByName(window.Name) == window):
            # Use a less-brittle global name-based query if one is available
            self._query = f'wx.FindWindowByName({repr(window.Name)})'  # type: str | None
        elif (window is not None and 
                (id_symbol_name := self._SYMBOL_NAME_FOR_WX_ID_VALUE.get(window.Id)) is not None and
                wx.FindWindowById(window.Id) == window):
            # Use a less-brittle global ID-based query if one is available
            self._query = f'wx.FindWindowById({id_symbol_name})'
        else:
            # Use fallback path-based query provided by caller
            self._query = query
    
    # === Formatting ===
    
    def __repr__(self) -> str:
        """
        Describes a CodeExpression to obtain this navigator's wx.Window
        and describes all of the window's visible descendents, including a
        CodeExpression to navigate to each descendent.
        """
        self_desc = (
            f'# {self._path}.{self._PEER_ACCESSOR} := {self._describe(self._peer)}\n'
            if self._peer is not None
            else None
        )
        children_desc = '\n'.join(self._describe_children(self._peer, self._path))
        return (
            self_desc + children_desc
            if self_desc is not None
            else children_desc
        )
    
    @classmethod
    def _describe_children(cls,
            parent: wx.Window | None,
            path: str,
            ) -> list[str]:
        children = cls._children_of(parent)
        tree_item_root = (
            TreeItem.GetRootItem(parent)
            if isinstance(parent, wx.TreeCtrl)
            else None
        )
        if len(children) == 0 and tree_item_root is None:
            return ['{}']
        else:
            modal_tlws = [
                tlw for tlw in wx.GetTopLevelWindows()
                if isinstance(tlw, wx.Dialog) and tlw.IsModal()
            ] if parent is None else []
            
            lines = []
            lines.append('{')
            if tree_item_root is not None:
                c = tree_item_root
                c_path = f'{path}.Tree'
                inner_lines = TreeItemNavigator._describe_children(c, c_path)
                inner_lines[0] = f'({c_path} := {TreeItemNavigator._describe(c)}): ' + inner_lines[0]
                for x in inner_lines:
                    lines.append(f'  {x}')
                lines[-1] += ','
            
            for i in range(min(len(children), 7)):
                if len(children) > 7:
                    # Insert a More(...) item in the center of the children list
                    # such that no more than 7 children are displayed by default
                    if i < 3:
                        c_index = i
                        # (keep going)
                    elif i == 3:
                        inner_line = f'More(Count={len(children) - 6})'
                        lines.append(f'  {inner_line}')
                        lines[-1] += ','
                        continue
                    elif i > 3:
                        c_index = len(children) - 3 + (i - 4)
                        # (keep going)
                else:
                    # Display the full children list
                    c_index = i
                c = children[c_index]
                
                c_path = f'{path}[{c_index}]'
                if modal_tlws and c not in modal_tlws:
                    # Elide tree for a top-level window that isn't interactable
                    # because some other modal window is visible
                    inner_lines = ['{ ... }']
                else:
                    inner_lines = cls._describe_children(c, c_path)
                inner_lines[0] = f'({c_path}.{cls._PEER_ACCESSOR} := {cls._describe(c)}): ' + inner_lines[0]
                for x in inner_lines:
                    lines.append(f'  {x}')
                lines[-1] += ','
            lines.append('}')
            return lines
    
    @classmethod
    def _describe(cls, peer: wx.Window) -> str:
        win = peer
        
        # Identify friendly class name for the window,
        # like 'wx.Frame' or 'wx.Button'
        win_type = type(win)
        win_type_str = (
            f'wx.{win_type.__name__}'
            if win_type.__module__ == 'wx._core'
            else f'{win_type.__module__}.{win_type.__name__}'
        )
        
        # Identify key identifying & descriptive attributes
        details = []  # type: list[tuple[str, str]]
        if not win.Shown:
            details.append(('Shown', repr(False)))
        if isinstance(win, wx.Dialog) and win.IsModal():
            details.append(('IsModal', repr(True)))
        if isinstance(win, wx.TopLevelWindow) and win.IsFullScreen():
            details.append(('IsFullScreen', repr(True)))
        default_name = cls._DEFAULT_NAME_FOR_WINDOW_TYPE_STR.get(win_type)
        if default_name is None or win.Name != default_name:
            # NOTE: If default Name for the window type isn't known, conservatively
            #       always advertise the name, even if it might be the default
            details.append(('Name', repr(win.Name)))
        if (id_symbol_name := cls._SYMBOL_NAME_FOR_WX_ID_VALUE.get(win.Id)) is not None:
            details.append(('Id', id_symbol_name))
        if win.Label:
            details.append(('Label', repr(win.Label)))
        if hasattr(win, 'Value'):
            details.append(('Value', repr(win.Value)))
        
        # Format constructor-like call syntax with key details
        description = f'{win_type_str}(' + ', '.join([
            f'{k}={v}'
            for (k, v) in details
        ]) + ')'
        return (
            description
            if description != 'wx.Panel()'
            # Minimize description of anonymous wx.Panels, which aren't very interesting
            else '_'
        )
    
    # === Navigation ===
    
    def __call__(self,
            *, Name: str | None = None,
            Id: str | None = None,
            Label: str | None = None,
            ) -> WindowNavigator | None:
        kwarg_count = (Name is not None) + (Id is not None) + (Label is not None)
        if kwarg_count != 1:
            raise ValueError('Provide exactly 1 kwarg: Name, Id, Label')
        if Name is not None:
            return self._find(
                Name,
                wx.Window.FindWindowByName,
                'wx.Window.FindWindowByName',
                index_path=f'{self._path}[{repr(Name)}]',
            )
        if Id is not None:
            index_repr = self._SYMBOL_NAME_FOR_WX_ID_VALUE.get(Id, str(Id))
            return self._find(
                Id,
                wx.Window.FindWindowById,
                'wx.Window.FindWindowById',
                index_repr=index_repr,
                index_path=f'{self._path}(Id={index_repr})',
            )
        if Label is not None:
            return self._find(
                Label,
                wx.Window.FindWindowByLabel,
                'wx.Window.FindWindowByLabel',
                index_path=f'{self._path}(Label={repr(Label)})',
            )
        raise AssertionError('unreachable')
    
    @overload
    def __getitem__(self, index: int) -> WindowNavigator: ...
    @overload
    def __getitem__(self, index: str) -> WindowNavigator | None: ...
    @overload
    def __getitem__(self, index: slice) -> NavigatorSlice[wx.Window]: ...
    def __getitem__(self, index: int | str | slice):
        """
        - navigator[i], where i is an int, returns a navigator pointing to
          the i'th visible child of this navigator's window.
        - navigator['cr-name'], where 'cr-name' is a Name of a window,
          returns a navigator pointing to the first visible descendent with a
          matching Name, or None if no match was found.
        - navigator[i:j:k], where i:j:k is a slice, returns navigators
          corresponding to the associated children of this navigator's window.
        """
        if isinstance(index, int):
            c_peer = self._children_of(self._peer)[index]
            c_path = f'{self._path}[{index}]'
            c_query = (
                f'{self._query}.Children[{self._all_children_of(self._peer).index(c_peer)}]'
                if self._query is not None
                else f'wx.GetTopLevelWindows()[{self._all_children_of(self._peer).index(c_peer)}]'
            )
            return WindowNavigator(c_peer, c_path, c_query)
        elif isinstance(index, str):
            return self._find(
                index,
                wx.Window.FindWindowByName,
                'wx.Window.FindWindowByName',
            )
        elif isinstance(index, slice):
            children = self._children_of(self._peer)  # cache
            all_children = self._all_children_of(self._peer)  # cache
            items = [
                WindowNavigator(
                    window=children[i],
                    path=f'{self._path}[{i}]',
                    query=(
                        f'{self._query}.Children[{all_children.index(children[i])}]'
                        if self._query is not None
                        else f'wx.GetTopLevelWindows()[{all_children.index(children[i])}]'
                    ),
                )
                for i in range(index.start or 0, index.stop or len(children), index.step or 1)
            ]
            return NavigatorSlice(index.start or 0, items, self._path)
        else:
            assert_never(index)
    
    def _find(self,
            index: str,
            finder: Callable,
            finder_str: str,
            *, index_repr: str | None = None,
            index_path: str | None = None,
            ) -> WindowNavigator | None:
        if index_repr is None:  # auto
            index_repr = repr(index)
        if index_path is None:  # auto
            index_path = f'{self._path}[{index_repr}]'
        
        children = self._children_of(self._peer)  # cache
        for c in children:
            found = finder(index, parent=c)
            if found is not None:
                return WindowNavigator(
                    window=found,
                    path=index_path,
                    query=(
                        f'{finder_str}({index_repr}, parent={self._query})'
                        if self._query is not None
                        else f'{finder_str}({index_repr})'
                    ),
                )
        return None
    
    def __len__(self) -> int:
        """
        The number of visible children of this navigator's window.
        """
        return len(self._children_of(self._peer))
    
    @property
    def Tree(self) -> TreeItemNavigator:
        """
        Returns a navigator pointing to the root TreeItem of this
        navigotor's wx.TreeCtrl.
        
        Raises:
        * NotATreeCtrl
        """
        if not isinstance(self._peer, wx.TreeCtrl):
            raise NotATreeCtrl()
        return TreeItemNavigator(
            TreeItem.GetRootItem(self._peer),
            f'{self._path}.Tree',
            f'TreeItem.GetRootItem({self._query})',
        )
    
    # === Children ===
    
    @classmethod
    def _children_of(cls,
            window: wx.Window | None,
            *, include_top_level: bool | None = None,
            include_hidden: bool = False,
            ) -> list[wx.Window]:
        if include_top_level is None:  # auto
            # By default only include top-level children when navigating at the top-level
            include_top_level = (window is None)
        
        children = cls._all_children_of(window)
        if not include_top_level:
            children = [c for c in children if not c.IsTopLevel()]
        if not include_hidden:
            children = [c for c in children if c.Shown]
        return children
    
    @classmethod
    def _all_children_of(cls, window: wx.Window | None) -> list[wx.Window]:
        if window is None:
            return wx.GetTopLevelWindows()
        else:
            return window.Children
    
    # === Properties ===
    
    _PEER_ACCESSOR = 'W'
    
    @property
    def Window(self) -> wx.Window:
        """
        The wx.Window that this navigator is pointing to.
        
        If this navigator is at the top and has no associated wx.Window
        a TopWindowNavigatorHasNoWindow exception will be raised.
        
        Raises:
        * TopWindowNavigatorHasNoWindow
        """
        if self._peer is None:
            raise TopWindowNavigatorHasNoWindow()
        return self._peer
    
    @property
    def W(self) -> wx.Window:
        """
        Shorthand property equivalent to .Window, for quick scripts.
        """
        return self.Window
    
    @property
    def Query(self) -> CodeExpression:
        """
        A code expression suitable for including in production code
        which returns this navigator's window.
        
        If this navigator is at the top and has no associated wx.Window
        a TopWindowNavigatorHasNoWindow exception will be raised.
        
        Raises:
        * TopWindowNavigatorHasNoWindow
        """
        if self._query is None:
            raise TopWindowNavigatorHasNoWindow()
        return CodeExpression(self._query)
    
    @property
    def Q(self) -> CodeExpression:
        """
        Shorthand property equivalent to .Query, for quick scripts.
        """
        return self.Query


class TopWindowNavigatorHasNoWindow(ValueError):
    pass


class NotATreeCtrl(ValueError):
    pass


# ------------------------------------------------------------------------------
# TreeItemNavigator

class TreeItemNavigator(Navigator[TreeItem]):
    """
    Points to a TreeItem, a wx.TreeItemId in a wx.TreeCtrl.
    Shows the item's tree of descendents when printed.
    
    When viewed as a Sequence, returns a TreeItemNavigator to navigate to each of the
    item's direct children. See __getitem__() documentation for all ways
    to navigate.
    """
    
    # === Init ===

    def __init__(self, item: TreeItem, path: str, query: str) -> None:
        """
        Creates a navigator. Most code will obtain a navigator by navigating
        from the top navigator `T` rather than creating one directly.
        """
        self._peer = item
        self._path = path
        self._query = query
    
    # === Formatting ===
    
    def __repr__(self) -> str:
        """
        Describes a CodeExpression to obtain this navigator's TreeItem
        and describes all of the item's visible descendents, including a
        CodeExpression to navigate to each descendent.
        """
        self_desc = (
            f'# {self._path}.{self._PEER_ACCESSOR} := {self._describe(self._peer)}\n'
        )
        children_desc = '\n'.join(self._describe_children(self._peer, self._path))
        return (
            self_desc + children_desc
        )
    
    @classmethod
    def _describe_children(cls,
            parent: TreeItem,
            path: str,
            ) -> list[str]:
        children = cls._children_of(parent)
        if len(children) == 0:
            return ['{}']
        else:
            lines = []
            lines.append('{')
            for i in range(min(len(children), 7)):
                if len(children) > 7:
                    # Insert a More(...) item in the center of the children list
                    # such that no more than 7 children are displayed by default
                    if i < 3:
                        c_index = i
                        # (keep going)
                    elif i == 3:
                        inner_line = f'More(Count={len(children) - 6})'
                        lines.append(f'  {inner_line}')
                        lines[-1] += ','
                        continue
                    elif i > 3:
                        c_index = len(children) - 3 + (i - 4)
                        # (keep going)
                else:
                    # Display the full children list
                    c_index = i
                c = children[c_index]
                
                c_path = f'{path}[{c_index}]'
                inner_lines = cls._describe_children(c, c_path)
                inner_lines[0] = f'({c_path}.{cls._PEER_ACCESSOR} := {cls._describe(c)}): ' + inner_lines[0]
                for x in inner_lines:
                    lines.append(f'  {x}')
                lines[-1] += ','
            lines.append('}')
            return lines
    
    @classmethod
    def _describe(cls, peer: TreeItem) -> str:
        item = peer
        item_is_root = item.IsRoot()  # cache
        hidden = (
            item_is_root and 
            (item.tree.WindowStyle & wx.TR_HIDE_ROOT) != 0
        )
        
        if item.ItemHasChildren():
            if item.IsExpanded():
                prefix = '▼ 📂 '  # down triangle + open folder
            else:
                prefix = '▶︎ 📁 '  # left triangle + closed folder
        else:
            prefix = '— 📄 ' # m-dash + file
        
        # Identify key identifying & descriptive attributes
        details = []  # type: list[tuple[str, str]]
        if not hidden:
            details.append(('👁', repr(f'{prefix}{item.Text}')))  # 👁 == LooksLike
        if item_is_root:
            details.append(('IsRoot', repr(True)))
        if hidden:
            details.append(('Visible', repr(False)))
        if item.IsSelected():
            details.append(('IsSelected', repr(True)))
        if (c := item.TextColour).IsOk():
            hex_color_str = f'#{c.Red():02x}{c.Green():02x}{c.Blue():02x}'
            details.append(('TextColour', repr(hex_color_str)))
        if item.Bold:
            details.append(('IsBold', repr(True)))
        
        # Format constructor-like call syntax with key details
        description = f'TreeItem(' + ', '.join([
            f'{k}={v}'
            for (k, v) in details
        ]) + ')'
        return description
    
    # === Navigation ===
    
    @overload
    def __getitem__(self, index: int) -> TreeItemNavigator: ...
    @overload
    def __getitem__(self, index: slice) -> NavigatorSlice[TreeItem]: ...
    def __getitem__(self, index: int | slice):
        """
        - navigator[i], where i is an int, returns a navigator pointing to
          the i'th visible child of this navigator's item.
        - navigator[i:j:k], where i:j:k is a slice, returns navigators
          corresponding to the associated children of this navigator's item.
        """
        if isinstance(index, int):
            c_peer = self._children_of(self._peer)[index]
            c_path = f'{self._path}[{index}]'
            c_query = (
                f'{self._query}.Children[{self._all_children_of(self._peer).index(c_peer)}]'
            )
            return TreeItemNavigator(c_peer, c_path, c_query)
        elif isinstance(index, slice):
            children = self._children_of(self._peer)  # cache
            all_children = self._all_children_of(self._peer)  # cache
            items = [
                TreeItemNavigator(
                    item=children[i],
                    path=f'{self._path}[{i}]',
                    query=(
                        f'{self._query}.Children[{all_children.index(children[i])}]'
                    ),
                )
                for i in range(index.start or 0, index.stop or len(children), index.step or 1)
            ]
            return NavigatorSlice(index.start or 0, items, self._path)
        else:
            assert_never(index)
    
    def __len__(self) -> int:
        """
        The number of visible children of this navigator's item.
        """
        return len(self._children_of(self._peer))
    
    # === Children ===
    
    @classmethod
    def _children_of(cls,
            item: TreeItem,
            ) -> list[TreeItem]:
        if item.IsExpanded() or item.IsRoot():
            return cls._all_children_of(item)
        else:
            return []
    
    @classmethod
    def _all_children_of(cls,
            item: TreeItem,
            ) -> list[TreeItem]:
        return item.Children
    
    # === Properties ===
    
    _PEER_ACCESSOR = 'I'
    
    @property
    def Item(self) -> TreeItem:
        """
        The TreeItem that this navigator is pointing to.
        """
        return self._peer
    
    @property
    def I(self) -> TreeItem:
        """
        Shorthand property equivalent to .Item, for quick scripts.
        """
        return self.Item
    
    @property
    def Query(self) -> CodeExpression:
        """
        A code expression suitable for including in production code
        which returns this navigator's item.
        """
        return CodeExpression(self._query)
    
    @property
    def Q(self) -> CodeExpression:
        """
        Shorthand property equivalent to .Query, for quick scripts.
        """
        return self.Query


# ------------------------------------------------------------------------------
# NavigatorSlice

# TODO: Fix tuple-missing-parens to not flag the next line improperly
class NavigatorSlice(Generic[_P], tuple[Navigator[_P], ...]):  # pylint: disable=tuple-missing-parens
    """
    A subrange of a navigator's children. Shows the subrange when printed.
    """
    _start: int
    _path: str
    
    def __new__(cls, start: int, items: Iterable[Navigator[_P]], path: str) -> 'NavigatorSlice':
        self = super().__new__(cls, tuple(items))  # type: ignore[arg-type, type-var]
        self._start = start
        self._path = path
        return self
    
    def __repr__(self) -> str:
        return '\n'.join(self._describe_items())
    
    def _describe_items(self) -> list[str]:
        items = self
        if len(items) == 0:
            return ['{}']
        else:
            path = self._path  # cache
            N = type(items[0])
            
            lines = []
            lines.append('{')
            for (c_index, c) in enumerate(items, start=self._start):
                c_path = f'{path}[{c_index}]'
                inner_lines = N._describe_children(c._peer, c_path)
                inner_lines[0] = f'({c_path}.{N._PEER_ACCESSOR} := {N._describe(c._peer)}): ' + inner_lines[0]
                for x in inner_lines:
                    lines.append(f'  {x}')
                lines[-1] += ','
            lines.append('}')
            return lines


# ------------------------------------------------------------------------------
# Utility: CodeExpression

class CodeExpression:
    """Represents a Python code expression. Shows the expression when printed."""
    
    def __init__(self, expr: str) -> None:
        self._expr = expr
    
    def __repr__(self) -> str:
        return self._expr
    
    def __str__(self) -> str:
        return self._expr


# ------------------------------------------------------------------------------
# Globals

# NOTE: This constant is exposed to AI agents in the shell
T = WindowNavigator()
T.__doc__ = (
    """
    The top navigator, pointing to the root of the wx.Window hierarchy.
    
    The repr() of the top navigator provides an snapshot of all visible
    windows in the wxPython application.
    
    The children of the top navigator correspond to all visible top-level windows.
    
    Examples
    ========
    
    Look at the UI:
        >>> T
        {
          (T[0].W := wx.Frame(Name='cr-main-window', Label='Untitled Project')): {
            (T[0][0].W := _): {
              ...
              (T[0][0][1].W := wx.Panel(Name='cr-status-bar')): {
                (T[0][0][1][0].W := wx.Panel(Name='cr-branding-area')): { ... },
                (T[0][0][1][1].W := wx.Button(Name='cr-preferences-button', Label='⚙️ Settings...')): {},
                (T[0][0][1][2].W := wx.StaticText(Name='cr-read-write-icon', Label='✏️')): {},
              },
            },
          },
        }
    
    Zoom in on part of the UI:
        >>> T[0][0][1]  # lookup by index
        # T[0][0][1].W := wx.Panel(Name='cr-status-bar')
        {
          (T[0][0][1][0].W := wx.Panel(Name='cr-branding-area')): { ... },
          (T[0][0][1][1].W := wx.Button(Name='cr-preferences-button', Label='⚙️ Settings...')): {},
          (T[0][0][1][2].W := wx.StaticText(Name='cr-read-write-icon', Label='✏️')): {},
        }
        
        >>> T['cr-preferences-button']  # lookup by Name
        >>> T(Id=wx.ID_YES)  # lookup by Id
        >>> T(Label='✏️')  # lookup by Label
    
    Click a button, checkbox, or radio button:
        >>> click(T(Id=wx.ID_YES).W)
        >>> click(T(Label='Open as &read only').W)
        >>> click(T['cr-preferences-dialog__no-proxy-radio'].W)
    
    Type in an input field:
        >>> T['cr-new-root-url-dialog__url-field'].W.Value = 'https://xkcd.com/'
        >>> T['cr-new-root-url-dialog__url-field'].W.Value
        'https://xkcd.com/'
    
    Manipulate a TreeItem:
        >>> T['cr-entity-tree'].Tree[0].I.Expand()
        >>> T['cr-entity-tree'].Tree[0][0].I.SelectItem()
        >>> T['cr-entity-tree'].Tree[0].I.Collapse()
        >>> help(TreeItem)  # for more methods and properties
    
    Obtain a query for a wx.Window/TreeItem for use in production code:
        >>> T['cr-entity-pane'].Q
        wx.FindWindowByName('cr-entity-pane')
        >>> T(Id=wx.ID_YES).Q
        wx.FindWindowById(wx.ID_YES)
        >>> T[0][0][0][0][1].Tree[0].Q
        TreeItem.GetRootItem(wx.FindWindowByName('cr-entity-tree')).Children[0]
    """
)


# ------------------------------------------------------------------------------
