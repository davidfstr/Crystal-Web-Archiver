"""
Provides a Python interface for easily navigating/viewing/controlling a
wxPython-based program.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
# TODO: Promote the TreeItem abstraction to the crystal.ui package,
#       outside of the crystal.tests.** namespace
from crystal.tests.util.controls import TreeItem
from crystal.util.xthreading import fg_affinity
from crystal.util.xtyping import not_none
from difflib import SequenceMatcher
import re
from typing import (
    Any, assert_never, Generic, Iterable, Literal, NoReturn, overload, Self,
    TypeAlias, TypeVar
)
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
    # Attributes that can be set on this class
    # NOTE: Not using __slots__ here because it prevents setting __doc__
    _ALLOWED_ATTRS = frozenset({'_peer', '__doc__'})
    
    _peer: _P
    
    def __setattr__(self, name: str, value: Any) -> None:
        """Prevent accidental assignment to any non-existent attribute."""
        for cls in type(self).__mro__:
            allowed: frozenset[str] = getattr(cls, '_ALLOWED_ATTRS', frozenset())
            if name in allowed:
                object.__setattr__(self, name, value)
                return
        raise AttributeError(
            f'Cannot set attribute {name!r} on {type(self).__name__!r} object'
        )
    
    # === Formatting ===
    
    def __repr__(self) -> str:
        """
        Describes a CodeExpression to obtain this navigator's peer
        and describes all of the peer's visible descendents, including a
        CodeExpression to navigate to each descendent.
        """
        raise NotImplementedError()
    
    @fg_affinity
    def snapshot(self) -> Snapshot[_P]:
        """
        Creates a snapshot of this navigator's state, recursively capturing
        all visible children.
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
    def Peer(self) -> _P:
        """
        The peer that this navigator is pointing to.
        """
        return getattr(self, self._PEER_ACCESSOR)
    
    @property
    def P(self) -> wx.Window:
        """
        Shorthand property equivalent to .Peer, for quick scripts.
        """
        return self.Peer
    
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
    # Attributes that can be set on this class
    _ALLOWED_ATTRS = frozenset({'_path', '_query'})
    
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

    def __init__(self,
            window: wx.Window | None = None,
            path: str = 'T',
            query: str | None = None,
            ) -> None:
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
        return repr(self.snapshot())
    
    @fg_affinity
    def snapshot(self) -> Snapshot[wx.Window]:
        """
        Creates a snapshot of this navigator's state, recursively capturing
        all visible children.
        
        Special handling:
        - Includes TreeItem root as a special child if the window is a TreeCtrl
        - Elides non-modal windows when modal dialogs are present
        """
        return self._snapshot_for(self._peer, self._path, self._query)
    
    @classmethod
    def _snapshot_for(cls,
            peer: wx.Window | None,
            path: str,
            query: str | None,
            ) -> Snapshot[wx.Window]:
        # Get peer description (may be '' for top-level navigator)
        peer_description = cls._describe(peer) if peer is not None else ''
        
        # Get children
        children = cls._children_of(peer)
        
        # Check for TreeCtrl with root item
        tree_item_root = (
            TreeItem.GetRootItem(peer)
            if isinstance(peer, wx.TreeCtrl)
            else None
        )
        
        # Identify modal top-level windows if we're at the top level
        modal_tlws = [
            tlw for tlw in wx.GetTopLevelWindows()
            if isinstance(tlw, wx.Dialog) and tlw.IsModal()
        ] if peer is None else []
        
        # Build child snapshots
        all_children_list = cls._all_children_of(peer)
        child_snapshots: list[Snapshot[wx.Window]] = []
        
        # Add TreeItem root as first "child" if present
        if tree_item_root is not None:
            tree_snapshot = TreeItemNavigator._snapshot_for(
                peer=tree_item_root,
                path=f'{path}.Tree',
                query=(
                    f'TreeItem.GetRootItem({query})'
                    if query
                    else f'TreeItem.GetRootItem(wx.GetTopLevelWindows()[...])'
                ),
            )
            child_snapshots.append(tree_snapshot)  # type: ignore[arg-type]
        
        # Add regular window children
        for (i, c) in enumerate(children):
            c_query = (
                f'{query}.Children[{all_children_list.index(c)}]'
                if query is not None
                else f'wx.GetTopLevelWindows()[{all_children_list.index(c)}]'
            )
            
            c_snapshot: Snapshot[wx.Window]
            if modal_tlws and c not in modal_tlws:
                # Create a shallow snapshot for non-interactable windows
                c_snapshot = Snapshot(
                    peer_description=cls._describe(c),
                    children=[],  # Empty - elided
                    children_elided=True,
                    path=f'{path}[{i}]',
                    query=c_query,
                    peer_accessor=cls._PEER_ACCESSOR,
                    peer_obj=c,
                )
            else:
                # Recursively create full snapshot
                c_snapshot = cls._snapshot_for(
                    peer=c,
                    path=f'{path}[{i}]',
                    query=c_query,
                )
            child_snapshots.append(c_snapshot)
        
        return Snapshot(
            peer_description=peer_description,
            children=child_snapshots,
            path=path,
            query=query or 'T',
            peer_accessor=cls._PEER_ACCESSOR,
            peer_obj=peer,
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
                        inner_line = f'({path}[{3}:{len(children)-3}] := More(Count={len(children) - 6})): [...]'
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
        if isinstance(window, wx.TreeCtrl):
            # Filter out scrollbars & other unimportant child windows that
            # sometimes show themselves and sometimes don't.
            # These windows just pollute snapshot diffs if retained.
            children = [c for c in children if not (
                # Filter out standalone scrollbar children
                (isinstance(c, wx.ScrollBar) and len(c.Children) == 0) or
                # Filter out empty panel child
                (c.Name == 'panel' and len(c.Children) == 0)
            )]
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
    # Attributes that can be set on this class
    _ALLOWED_ATTRS = frozenset({'_path', '_query'})
    
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
        return repr(self.snapshot())
    
    @fg_affinity
    def snapshot(self) -> Snapshot[TreeItem]:
        """
        Creates a snapshot of this navigator's state, recursively capturing
        all visible children.
        """
        return self._snapshot_for(self._peer, self._path, self._query)
    
    @classmethod
    def _snapshot_for(cls,
            peer: TreeItem,
            path: str,
            query: str,
            ) -> Snapshot[TreeItem]:
        peer_description = cls._describe(peer)
        children = cls._children_of(peer)
        
        # Recursively create snapshots for all children
        all_children_list = cls._all_children_of(peer)
        child_snapshots = [
            cls._snapshot_for(
                peer=c,
                path=f'{path}[{i}]',
                query=f'{query}.Children[{all_children_list.index(c)}]',
            )
            for (i, c) in enumerate(children)
        ]
        
        return Snapshot(
            peer_description=peer_description,
            children=child_snapshots,
            path=path,
            query=query,
            peer_accessor=cls._PEER_ACCESSOR,
            peer_obj=peer,
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
                        inner_line = f'({path}[{3}:{len(children)-3}] := More(Count={len(children) - 6})): [...]'
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
        if (icon_tooltip := item.Tooltip('icon')) is not None:
            details.append(('IconTooltip', repr(icon_tooltip)))
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
# Snapshot

DeletionStyle: TypeAlias = Literal['minimal', 'full']

_DEFAULT_DELETION_STYLE: DeletionStyle = 'minimal'

class Snapshot(Generic[_P], Sequence['Snapshot[_P]']):
    """
    A snapshot of a Navigator's state at a point in time.
    Used for detecting changes in the UI.
    
    Captures the full tree structure including all children,
    even those that would be hidden by More(...) in the repr output.
    
    Examples
    ========
    
    Create snapshots and detect changes:
        >>> # Take initial snapshot
        >>> snap1 = T['cr-entity-tree'].Tree.snapshot()
        >>> 
        >>> # Perform some UI actions...
        >>> # ...
        >>> 
        >>> # Take new snapshot
        >>> snap2 = T['cr-entity-tree'].Tree.snapshot()
        >>> 
        >>> # Detect what changed
        >>> diff = Snapshot.diff(snap1, snap2)
        >>> if diff:
        ...     print(repr(diff))
        # S := T['cr-entity-tree'].Tree
        S[0] ~ TreeItem(👁='... {27→31} of 2,438 ...')
        S[0][1][0] ~ TreeItem(👁='— 📄 2{2→6} more')
        ...
    """
    # NOTE: Prevent accidental assignment to any non-existent attribute
    __slots__ = (
        '_peer_description',
        '_children',
        '_children_elided',
        '_path',
        '_query',
        '_peer_accessor',
        '_peer_obj',
    )
    
    def __init__(self,
            peer_description: str,
            children: list['Snapshot[_P]'],
            path: str,
            query: str,
            peer_accessor: str,
            *, peer_obj: _P,
            children_elided: bool = False,
            ) -> None:
        """
        Creates a snapshot.
        
        Arguments:
        * peer_description -- The description of the peer from _describe()
        * children -- Snapshots of all visible children
        * path -- The navigation path to this peer
        * query -- The code expression to obtain this peer
        * peer_accessor -- The name of the shorthand property (e.g., 'I', 'W')
        * peer_obj --
            The peer which this snapshot is rooted at.
            Expected to be hashable.
        """
        self._peer_description = peer_description
        self._children = children
        self._children_elided = children_elided
        self._path = path
        self._query = query
        self._peer_accessor = peer_accessor
        self._peer_obj = peer_obj
    
    # === Format ===
    
    def __repr__(self) -> str:
        """
        Returns a formatted representation of this snapshot and its children,
        using the same format as Navigator.__repr__().
        """
        # Top-level navigator (e.g., T) doesn't show self description
        self_desc = (
            f'# {self._path}.{self._peer_accessor} := {self._peer_description}\n'
            if self._peer_description != ''
            else None
        )
        children_desc = '\n'.join(self._describe_children())
        return (
            self_desc + children_desc
            if self_desc is not None
            else children_desc
        )
    
    def _describe_children(self) -> list[str]:
        """
        Formats the children of this snapshot,
        applying More(...) truncation logic when there are more than 7 children.
        """
        children = self._children
        path = self._path
        peer_accessor = self._peer_accessor
        children_elided = self._children_elided
        
        if len(children) == 0:
            if children_elided:
                return ['{...}']
            else:
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
                        inner_line = f'({path}[{3}:{len(children)-3}] := More(Count={len(children) - 6})): [...]'
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
                
                inner_lines = c._describe_children()
                inner_lines[0] = f'({c._path}.{c._peer_accessor} := {c._peer_description}): ' + inner_lines[0]
                for x in inner_lines:
                    lines.append(f'  {x}')
                lines[-1] += ','
            lines.append('}')
            return lines
    
    # === Navigation ===
    
    # TODO: Consider supporting index by string, to recursively search for a
    #       window with the specified string Name. This behavior would be
    #       consistent with (Window)Navigator's __getitem__ API.
    @overload
    def __getitem__(self, index: int) -> 'Snapshot[_P]': ...
    @overload
    def __getitem__(self, index: slice) -> tuple['Snapshot[_P]', ...]: ...
    def __getitem__(self, index: int | slice):
        """
        - snapshot[i], where i is an int, returns a snapshot of
          the i'th visible child of this snapshot's peer.
        - snapshot[i:j:k], where i:j:k is a slice, returns a tuple of snapshots
          corresponding to the associated children of this snapshot's peer.
        """
        if isinstance(index, int):
            return self._children[index]
        elif isinstance(index, slice):
            return tuple(self._children[index])
        else:
            raise TypeError(f'indices must be integers or slices, not {type(index).__name__}')
    
    def __len__(self) -> int:
        """
        The number of visible children of this snapshot's peer.
        """
        return len(self._children)
    
    # === Properties ===
    
    @property
    def Peer(self) -> _P:
        """
        The peer that this snapshot is rooted at.
        """
        return self._peer
    
    @property
    def P(self) -> wx.Window:
        """
        Shorthand property equivalent to .Peer, for quick scripts.
        """
        return self.Peer
    
    def __dir__(self) -> Iterable[str]:
        # Include {_peer_accessor} in the list of attributes
        return sorted(list(super().__dir__()) + [self._peer_accessor])
    
    def __getattr__(self, attr_name: str) -> Any:
        # Support access of {W, I} or whatever {_peer_accessor} is
        if attr_name == self._peer_accessor:
            return self._peer_obj
        raise AttributeError
    
    # === Diff ===
    
    @staticmethod
    def diff(
            old: 'Snapshot[_P]',
            new: 'Snapshot[_P]',
            name: str = 'S',
            deletion_style: DeletionStyle = _DEFAULT_DELETION_STYLE,
            ) -> 'SnapshotDiff[_P]':
        """
        Compares two snapshots and returns a SnapshotDiff describing all
        changes between them.
        
        Arguments:
        * old -- The old snapshot to compare from
        * new -- The new snapshot to compare to
        * name -- The root name to use in the diff output (default 'S')
        * deletion_style --
            How to display deleted nodes: 'full' shows all descendents,
            'minimal' collapses them
        
        Returns:
        * A SnapshotDiff object that can be printed to see all changes
        """
        def diff_rooted_here() -> 'SnapshotDiff[_P]':
            return SnapshotDiff(old, new, name, deletion_style)
        
        # If description of each snapshot's peer differs, diff root is here
        if old._peer_description != new._peer_description:
            return diff_rooted_here()
        
        # If either snapshot has children elided, skip comparing children entirely
        # Children are not fully captured, so we can't determine if they changed
        if old._children_elided or new._children_elided:
            # Return an empty diff since we can't detect child changes
            return diff_rooted_here()
        
        # If children count differs, diff root is here
        if len(old._children) != len(new._children):
            return diff_rooted_here()
        
        # If children identities differ, diff root is here
        for (c1, c2) in zip(old._children, new._children):
            if c1._peer_obj != c2._peer_obj:
                return diff_rooted_here()
        
        # Compare children recursively
        child_diffs: list[SnapshotDiff[_P] | None] = []
        for (c1, c2) in zip(old._children, new._children):
            child_diff = Snapshot.diff(c1, c2, deletion_style=deletion_style)
            child_diffs.append(child_diff)
        
        # Count non-empty diffs
        non_empty_diffs = [d for d in child_diffs if d]
        
        if len(non_empty_diffs) == 0:
            # If zero children have a non-empty diff, return an empty diff rooted here
            return diff_rooted_here()
        elif len(non_empty_diffs) == 1:
            # If exactly 1 child has a non-empty diff, return that diff
            return non_empty_diffs[0]
        else:
            # If multiple children have a non-empty diff, diff root is here
            return diff_rooted_here()
    
    def __sub__(new: Self, old: 'Snapshot[_P]') -> 'SnapshotDiff[_P]':
        """
        Shorthand operator equivalent to .diff, for quick scripts.
        
        Example:
            >>> snap_diff = new - old  # Snapshot.diff(old, new)
        """
        if not isinstance(old, Snapshot):
            return NotImplemented  # type: ignore[return-value]
        return Snapshot.diff(old, new)


# ------------------------------------------------------------------------------
# SnapshotDiff

class SnapshotDiff(Generic[_P]):
    """
    Represents the difference between two snapshots.
    
    Provides a concise, readable representation of what changed between
    the old and new snapshots.
    
    Examples
    ========
    
    Create and display a diff:
        >>> snap1 = T['cr-entity-tree'].Tree.snapshot()
        >>> # ... perform UI actions ...
        >>> snap2 = T['cr-entity-tree'].Tree.snapshot()
        >>> 
        >>> diff = Snapshot.diff(snap1, snap2)
        >>> print(repr(diff))
        # S := T['cr-entity-tree'].Tree[0]
        S ~ TreeItem(👁='... {27→31} of 2,438 ...')
        S[1][0] ~ TreeItem(👁='— 📄 2{2→6} more')
        ...
    
    Access the underlying snapshots:
        >>> diff.old  # The old snapshot
        >>> diff.new  # The new snapshot
    """
    # NOTE: Prevent accidental assignment to any non-existent attribute
    __slots__ = (
        '_old',
        '_new',
        '_name',
        '_deletion_style',
    )
    
    def __init__(self,
            old: Snapshot[_P],
            new: Snapshot[_P],
            name: str = 'S',
            deletion_style: DeletionStyle = _DEFAULT_DELETION_STYLE,
            ) -> None:
        self._old = old
        self._new = new
        self._name = name
        self._deletion_style = deletion_style
    
    # === Format ===
    
    def __repr__(self) -> str:
        """
        Returns a concise diff representation showing all changes.
        
        Format:
        - Header: `# S := path.to.root`
        - Modified: `S[...] ~ Description({old→new})`
        - Removed: `S[...] - Description`
        - Added: `S[...] + Description`
        - Unchanged but moved: `S[old→new] = Description`
        - Range slide: `S[a..b → c..d] = More(Count=N)`
        - Collapsed additions: `S[a..b] + More(Count=N)` (for runs > 7)
        - Collapsed deletions: `S[a..b] - More(Count=N)` (for runs > 7)
        """
        entries = self._compute_diff_entries(
            self._old,
            self._new,
            self._name,
            self._deletion_style,
        )
        # Sort all entries by path for proper tree ordering
        entries.sort(key=lambda e: e.path_sort_key())
        
        # Collapse various types of runs into More(...) entries
        entries = self._collapse_shifted_unchanged_runs(entries)
        entries = self._collapse_add_and_delete_runs(entries)
        
        lines = [f'# {self._name} := {self._new._path}']
        if entries:
            for entry in entries:
                lines.extend(entry.format_lines())
        else:
            lines.append('(no changes)')
        return '\n'.join(lines)
    
    @classmethod
    def _compute_diff_entries(cls,
            old: Snapshot[_P],
            new: Snapshot[_P],
            path: str,
            deletion_style: DeletionStyle,
            ) -> list['_DiffEntry']:
        """
        Recursively computes all diff entries between two snapshots.
        """
        entries: list[_DiffEntry] = []
        
        # Check if root details changed
        if old._peer_description != new._peer_description:
            entries.append(_DiffEntry(
                path=path,
                symbol='~',
                description=inline_diff(old._peer_description, new._peer_description),
                old_index=None,
                new_index=None,
            ))
        
        # Compute child diffs
        # NOTE: If children are elided, assume nothing changed.
        if not old._children_elided and not new._children_elided:
            child_entries = cls._compute_children_diff(
                old._children,
                new._children,
                path,
                deletion_style,
            )
            entries.extend(child_entries)
        
        return entries
    
    @classmethod
    def _compute_children_diff(cls,
            old_children: list[Snapshot[_P]],
            new_children: list[Snapshot[_P]],
            parent_path: str,
            deletion_style: DeletionStyle,
            ) -> list['_DiffEntry']:
        """
        Computes diff entries for children of a node.
        Matches children by identity (peer_obj), then by description.
        """
        # Build mappings from peer_obj to (index, snapshot) for matching
        old_by_id: dict[Hashable, tuple[int, Snapshot[_P]]] = {}
        new_by_id: dict[Hashable, tuple[int, Snapshot[_P]]] = {}
        for (i, c) in enumerate(old_children):
            old_by_id[c._peer_obj] = (i, c)
        for (i, c) in enumerate(new_children):
            new_by_id[c._peer_obj] = (i, c)
        
        # Find matches, deletions, and additions
        if True:
            # Find matches
            matches: list[tuple[int, int, Snapshot[_P], Snapshot[_P]]] = []  # (old_idx, new_idx, old_snap, new_snap)
            matched_old_indices: set[int] = set()
            matched_new_indices: set[int] = set()
            if True:
                # Match by peer_obj
                for (peer_obj_id, (old_idx, old_snap)) in old_by_id.items():
                    if peer_obj_id in new_by_id:
                        (new_idx, new_snap) = new_by_id[peer_obj_id]
                        matches.append((old_idx, new_idx, old_snap, new_snap))
                        matched_old_indices.add(old_idx)
                        matched_new_indices.add(new_idx)
                
                # Fallback: Simple greedy matching by description for remaining items
                # NOTE: Previously this logic was necessary because peer_obj could be None,
                #       but None is no longer a valid value.
                remaining_old = [
                    (i, c) for (i, c) in enumerate(old_children)
                    if i not in matched_old_indices
                ]
                remaining_new = [
                    (i, c) for (i, c) in enumerate(new_children)
                    if i not in matched_new_indices
                ]
                for (old_idx, old_snap) in remaining_old:
                    for (new_idx, new_snap) in remaining_new:
                        if new_idx not in matched_new_indices:
                            if old_snap._peer_description == new_snap._peer_description:
                                matches.append((old_idx, new_idx, old_snap, new_snap))
                                matched_old_indices.add(old_idx)
                                matched_new_indices.add(new_idx)
                                break
            
            # Collect deletions (old children not matched)
            deletions = [
                (i, c) for (i, c) in enumerate(old_children)
                if i not in matched_old_indices
            ]
            
            # Collect additions (new children not matched)
            additions = [
                (i, c) for (i, c) in enumerate(new_children)
                if i not in matched_new_indices
            ]
        
        # Compute diff entries
        entries: list[_DiffEntry] = []
        if True:
            # Process matches: Check for modifications and index changes
            for (old_idx, new_idx, old_snap, new_snap) in matches:
                child_path = cls._format_child_path(parent_path, old_idx, new_idx)
                
                # Check if details changed
                details_changed = old_snap._peer_description != new_snap._peer_description
                index_changed = old_idx != new_idx
                
                if details_changed:
                    # Details changed. Index may have changed.
                    entries.append(_DiffEntry(
                        path=child_path,
                        symbol='~',
                        description=inline_diff(old_snap._peer_description, new_snap._peer_description),
                        old_index=old_idx,
                        new_index=new_idx,
                    ))
                elif index_changed:
                    # Index changed. Details the same.
                    entries.append(_DiffEntry(
                        path=child_path,
                        symbol='=',
                        description=new_snap._peer_description,
                        old_index=old_idx,
                        new_index=new_idx,
                    ))
                else:
                    # Neither details nor index changed
                    pass
                
                # Recursively diff children of matched nodes
                # NOTE: If children are elided, assume nothing changed.
                if not old_snap._children_elided and not new_snap._children_elided:
                    recursive_entries = cls._compute_children_diff(
                        old_snap._children,
                        new_snap._children,
                        f'{parent_path}[{new_idx}]',  # Use new index for path
                        deletion_style,
                    )
                    entries.extend(recursive_entries)
            
            # Add deletion entries
            for (old_idx, old_snap) in deletions:
                child_path = f'{parent_path}[{old_idx}]'
                # Recursively compute entries for all descendents of the removed node
                descendant_entries = cls._compute_descendant_entries(
                    old_snap,
                    child_path,
                    symbol='-',
                    deletion_style=deletion_style,
                )
                entries.append(_DiffEntry(
                    path=child_path,
                    symbol='-',
                    description=old_snap._peer_description,
                    old_index=old_idx,
                    new_index=None,
                    descendents=descendant_entries,
                ))
            
            # Add addition entries
            for (new_idx, new_snap) in additions:
                child_path = f'{parent_path}[{new_idx}]'
                # Recursively compute entries for all descendents of the added node
                descendant_entries = cls._compute_descendant_entries(
                    new_snap,
                    child_path,
                    symbol='+',
                    deletion_style=deletion_style,
                )
                entries.append(_DiffEntry(
                    path=child_path,
                    symbol='+',
                    description=new_snap._peer_description,
                    old_index=None,
                    new_index=new_idx,
                    descendents=descendant_entries,
                ))
        
        # NOTE: Returned entries are unsorted.
        #       Sorting is done at the top level in __repr__ using path_sort_key()
        return entries
    
    @classmethod
    def _compute_descendant_entries(cls,
            snapshot: Snapshot[_P],
            parent_path: str,
            symbol: Literal['+', '-'],
            deletion_style: DeletionStyle = _DEFAULT_DELETION_STYLE,
            ) -> list['_DiffEntry']:
        """
        Recursively compute diff entries for all descendents of a snapshot node.
        Used when a node is added or removed to show all its children.
        
        Arguments:
        * snapshot -- The snapshot node whose descendents to process
        * parent_path -- The path to the snapshot node in the diff output
        * symbol -- Either '+' (for added nodes) or '-' (for removed nodes)
        * deletion_style --
            How to display deleted nodes: 'full' shows all descendents,
            'minimal' collapses them
        
        Returns:
        * A list of _DiffEntry objects for all descendents
        """
        entries: list[_DiffEntry] = []
        
        # For minimal deletion style, collapse all children into a single More(...) entry
        if deletion_style == 'minimal' and symbol == '-':
            # Count total descendents recursively
            def count_descendents(snap: Snapshot[_P]) -> int:
                total = len(snap._children)
                for child in snap._children:
                    total += count_descendents(child)
                return total
            
            num_children = len(snapshot._children)
            if num_children > 0:
                # Create a collapsed entry for all children
                # Determine the path range
                if num_children == 1:
                    child_range_path = f'{parent_path}[0]'
                else:
                    child_range_path = f'{parent_path}[0..{num_children - 1}]'
                
                entries.append(_DiffEntry(
                    path=child_range_path,
                    symbol='-',
                    description=f'More(Count={num_children})',
                    old_index=0,
                    new_index=None,
                    old_range_end=num_children - 1 if num_children > 1 else None,
                ))
            return entries
        
        # For full deletion style or additions, show all descendents
        for (idx, child_snap) in enumerate(snapshot._children):
            child_path = f'{parent_path}[{idx}]'
            
            # Create an entry for this child
            if symbol == '+':
                entries.append(_DiffEntry(
                    path=child_path,
                    symbol='+',
                    description=child_snap._peer_description,
                    old_index=None,
                    new_index=idx,
                ))
            else:  # symbol == '-'
                entries.append(_DiffEntry(
                    path=child_path,
                    symbol='-',
                    description=child_snap._peer_description,
                    old_index=idx,
                    new_index=None,
                ))
            
            # Recursively process this child's descendents
            descendant_entries = cls._compute_descendant_entries(
                child_snap,
                child_path,
                symbol,
                deletion_style,
            )
            entries.extend(descendant_entries)
        
        return entries
    
    @classmethod
    def _format_child_path(cls,
            parent_path: str,
            old_idx: int,
            new_idx: int,
            ) -> str:
        """Format child path with index change notation if needed."""
        if old_idx == new_idx:
            return f'{parent_path}[{new_idx}]'
        else:
            return f'{parent_path}[{old_idx}→{new_idx}]'
    
    @classmethod
    def _collapse_shifted_unchanged_runs(cls, entries: list['_DiffEntry']) -> list['_DiffEntry']:
        """
        Merges contiguous moved nodes with unchanged details into range entries.
        
        Detects sequences of entries that:
        1. Have symbol '=' (moved but unchanged)
        2. Are at the same tree depth
        3. Have contiguous old and new indices
        4. Have the same parent path
        
        Merges such sequences into a single range entry with format:
        S[parent][A..B → C..D] = More(Count=N)
        
        Note: This method skips over non-'=' entries (additions/deletions/modifications)
        when looking for contiguous sequences, so that moves can be merged even if
        other changes are interspersed in the sorted output.
        """
        if len(entries) <= 1:
            return entries
        
        # First pass: identify which '=' entries belong to mergeable ranges
        # Group entries by parent path
        groups_by_parent: dict[str, list[tuple[int, _DiffEntry]]] = {}
        for (idx, entry) in enumerate(entries):
            if entry.symbol == '=':
                assert entry.old_index is not None
                assert entry.new_index is not None
                parent_path = cls._extract_parent_path(entry.path)
                if parent_path not in groups_by_parent:
                    groups_by_parent[parent_path] = []
                groups_by_parent[parent_path].append((idx, entry))
        
        # For each parent group, find contiguous ranges
        entries_to_merge: set[int] = set()  # Indices of entries that will be merged
        range_replacements: dict[int, _DiffEntry] = {}  # Maps first entry index to range entry
        
        for (parent_path, group) in groups_by_parent.items():
            # Sort by old_index to find contiguous sequences
            group.sort(key=lambda x: not_none(x[1].old_index))
            
            i = 0
            while i < len(group):
                (start_idx, start_entry) = group[i]
                range_entries = [(start_idx, start_entry)]
                
                # Try to extend the range
                j = i + 1
                while j < len(group):
                    (_, curr_entry) = range_entries[-1]
                    (next_idx, next_entry) = group[j]
                    
                    # Check if next entry continues the sequence
                    if (next_entry.old_index == not_none(curr_entry.old_index) + 1 and
                        next_entry.new_index == not_none(curr_entry.new_index) + 1):
                        range_entries.append((next_idx, next_entry))
                        j += 1
                    else:
                        break
                
                # If we found a range of at least 2 entries, mark them for merging
                if len(range_entries) >= 2:
                    first_entry = range_entries[0][1]
                    last_entry = range_entries[-1][1]
                    
                    # Create range path: S[parent][A..B → C..D]
                    range_path = f'{parent_path}[{first_entry.old_index}..{last_entry.old_index} → {first_entry.new_index}..{last_entry.new_index}]'
                    
                    # Create range description
                    range_desc = f'More(Count={len(range_entries)})'
                    
                    # Create the range entry
                    range_entry = _DiffEntry(
                        path=range_path,
                        symbol='=',
                        description=range_desc,
                        old_index=first_entry.old_index,
                        new_index=first_entry.new_index,
                        old_range_end=last_entry.old_index,
                        new_range_end=last_entry.new_index,
                    )
                    
                    # Mark all entries in this range for merging
                    for (entry_idx, _) in range_entries:
                        entries_to_merge.add(entry_idx)
                    
                    # The range entry will replace the first entry in the range
                    range_replacements[range_entries[0][0]] = range_entry
                
                i = j
        
        # Second pass: build the merged list
        merged: list[_DiffEntry] = []
        for (idx, entry) in enumerate(entries):
            if idx in entries_to_merge:
                # This entry is part of a merged range
                if idx in range_replacements:
                    # This is the first entry of a range, replace it with the range entry
                    merged.append(range_replacements[idx])
                # Otherwise, skip this entry (it's been merged into a range)
            else:
                # Keep this entry as-is
                merged.append(entry)
        
        return merged
    
    @classmethod
    def _extract_parent_path(cls, path: str) -> str:
        """
        Extracts the parent path from a full path.
        
        Examples:
            'S[0][1→2]' -> 'S[0]'
            'S[0][1]' -> 'S[0]'
            'S[0]' -> 'S'
        """
        # Find the last '[' and strip everything from there
        last_bracket = path.rfind('[')
        if last_bracket == -1:
            return ''
        return path[:last_bracket]
    
    @classmethod
    def _collapse_add_and_delete_runs(cls, entries: list['_DiffEntry']) -> list['_DiffEntry']:
        """
        Collapses long runs of additions (+) or deletions (-) into More() entries.
        
        If a contiguous range of > 7 indexes all have the same symbol (+ or -),
        every interior line except the first 3 and last 3 in the range
        is replaced with a More(Count=#) line.
        
        Example:
            S[0] + ...
            S[1] + ...
            S[2] + ...
            S[3..31] + More(Count=29)
            S[32] + ...
            S[33] + ...
            S[34] + ...
        """
        # Group entries by parent path and symbol (+ or -)
        groups_by_parent_symbol: dict[tuple[str, str], list[tuple[int, _DiffEntry]]] = {}
        for (idx, entry) in enumerate(entries):
            if entry.symbol in ('+', '-'):
                parent_path = cls._extract_parent_path(entry.path)
                key = (parent_path, entry.symbol)
                if key not in groups_by_parent_symbol:
                    groups_by_parent_symbol[key] = []
                groups_by_parent_symbol[key].append((idx, entry))
        
        # For each parent+symbol group, find contiguous runs to collapse
        entries_to_collapse: set[int] = set()  # Indices of entries that will be collapsed
        more_replacements: dict[int, _DiffEntry] = {}  # Maps collapse position to More entry
        
        for ((parent_path, symbol), group) in groups_by_parent_symbol.items():
            # Sort by index (use new_index for additions, old_index for deletions)
            if symbol == '+':
                group.sort(key=lambda x: not_none(x[1].new_index))
            else:  # symbol == '-'
                group.sort(key=lambda x: not_none(x[1].old_index))
            
            i = 0
            while i < len(group):
                (start_idx, start_entry) = group[i]
                run_entries = [(start_idx, start_entry)]
                
                # Try to extend the run
                j = i + 1
                while j < len(group):
                    (_, curr_entry) = run_entries[-1]
                    (next_idx, next_entry) = group[j]
                    
                    # Check if next entry continues the contiguous sequence
                    if symbol == '+':
                        curr_idx = not_none(curr_entry.new_index)
                        next_new_idx = not_none(next_entry.new_index)
                        if next_new_idx == curr_idx + 1:
                            run_entries.append((next_idx, next_entry))
                            j += 1
                        else:
                            break
                    else:  # symbol == '-'
                        curr_idx = not_none(curr_entry.old_index)
                        next_old_idx = not_none(next_entry.old_index)
                        if next_old_idx == curr_idx + 1:
                            run_entries.append((next_idx, next_entry))
                            j += 1
                        else:
                            break
                
                # If we found a run of > 7 entries, collapse the interior
                if len(run_entries) > 7:
                    # Keep first 3 and last 3, collapse the interior
                    first_3 = run_entries[:3]
                    last_3 = run_entries[-3:]
                    interior = run_entries[3:-3]
                    
                    # Create the More entry
                    first_interior_entry = interior[0][1]
                    last_interior_entry = interior[-1][1]
                    
                    if symbol == '+':
                        first_idx = not_none(first_interior_entry.new_index)
                        last_idx = not_none(last_interior_entry.new_index)
                        more_path = f'{parent_path}[{first_idx}..{last_idx}]'
                        more_entry = _DiffEntry(
                            path=more_path,
                            symbol='+',
                            description=f'More(Count={len(interior)})',
                            old_index=None,
                            new_index=first_idx,
                        )
                    else:  # symbol == '-'
                        first_idx = not_none(first_interior_entry.old_index)
                        last_idx = not_none(last_interior_entry.old_index)
                        more_path = f'{parent_path}[{first_idx}..{last_idx}]'
                        more_entry = _DiffEntry(
                            path=more_path,
                            symbol='-',
                            description=f'More(Count={len(interior)})',
                            old_index=first_idx,
                            new_index=None,
                        )
                    
                    # Mark interior entries for removal
                    for (entry_idx, _) in interior:
                        entries_to_collapse.add(entry_idx)
                    
                    # The More entry will replace the first interior entry
                    more_replacements[interior[0][0]] = more_entry
                
                i = j
        
        # Second pass: build the collapsed list
        collapsed: list[_DiffEntry] = []
        for (idx, entry) in enumerate(entries):
            if idx in entries_to_collapse:
                # This entry is part of a collapsed run
                if idx in more_replacements:
                    # This is the first interior entry, replace it with the More entry
                    collapsed.append(more_replacements[idx])
                # Otherwise, skip this entry (it's been collapsed into a More)
            else:
                # Keep this entry as-is
                collapsed.append(entry)
        
        return collapsed
    
    # === Empty ===
    
    def __bool__(self) -> bool:
        """Returns True if there are any changes, False otherwise."""
        entries = self._compute_diff_entries(
            self._old,
            self._new,
            self._name,
            self._deletion_style,
        )
        return len(entries) > 0
    
    # === Navigation ===
    
    def __getitem__(self, index: object) -> NoReturn:
        raise ValueError(
            f'{self._name}[{index!r}] is ambiguous. '
            f'Use {self._name}.new[{index!r}] or {self._name}.old[{index!r}] instead.'
        )
    
    @property
    def old(self) -> Snapshot[_P]:
        """The old snapshot being compared from."""
        return self._old
    
    @property
    def new(self) -> Snapshot[_P]:
        """The new snapshot being compared to."""
        return self._new


class _DiffEntry:
    """
    Represents a single line in a snapshot diff output.
    May contain nested descendent entries that should be printed after this entry.
    """
    # NOTE: Minimize memory usage
    __slots__ = (
        'path',
        'symbol',
        'description',
        'old_index',
        'new_index',
        'old_range_end',
        'new_range_end',
        'descendents',
    )
    
    def __init__(self,
            path: str,
            symbol: Literal['~', '-', '+', '='],
            description: str,
            old_index: int | None,
            new_index: int | None,
            *,
            old_range_end: int | None = None,
            new_range_end: int | None = None,
            descendents: list['_DiffEntry'] | None = None,
            ) -> None:
        self.path = path
        self.symbol = symbol
        self.description = description
        self.old_index = old_index
        self.new_index = new_index
        self.old_range_end = old_range_end
        self.new_range_end = new_range_end
        self.descendents = descendents or []
    
    def format_lines(self) -> list[str]:
        """Format this entry and all its descendents as diff lines."""
        lines = [f'{self.path} {self.symbol} {self.description}']
        # Recursively format all descendent entries
        for desc in self.descendents:
            lines.extend(desc.format_lines())
        return lines
    
    def path_sort_key(self) -> tuple:
        """
        Returns a sort key for ordering entries by path.
        
        Parses the path into segments and sorts by:
        - Each path segment's index (old_index if present, else new_index)
        - For entries at the same position, additions (+) come after others
        """
        # Parse path segments like S[0][1][2→3] into indices
        segments = re.findall(r'\[(\d+)(?:→(\d+))?\]', self.path)
        
        # Build sort key: for each segment, use old_index if present, else new_index
        indices: list[int] = []
        for seg in segments:
            (old_idx_str, new_idx_str) = seg
            # Use old index if present (for moved items), else use the index as-is
            idx = int(old_idx_str) if old_idx_str else int(new_idx_str or 0)
            indices.append(idx)
        
        # Additions at the same path position come after other symbols
        addition_penalty = 1 if self.symbol == '+' else 0
        
        return (tuple(indices), addition_penalty, self.path)


# ------------------------------------------------------------------------------
# Utility: Inline Diff

def inline_diff(old: str, new: str) -> str:
    """
    Computes an inline diff between two strings, marking changes with {old→new}.
    
    Uses a token-based diff algorithm to avoid splitting words and numbers in
    the middle. Tokens are defined as:
    - Runs of letters [a-zA-Z]+
    - Runs of digits and formatting chars [\\d:,.]+
    - Single characters (anything else)
    
    Examples:
        >>> inline_diff("hello world", "hello there")
        'hello {world→there}'
        >>> inline_diff("27 of 100", "31 of 100")
        '{27→31} of 100'
        >>> inline_diff("Downloading", "Complete")
        '{Downloading→Complete}'
        >>> inline_diff("2:18:01", "2:19:18")
        '{2:18:01→2:19:18}'
    """
    if old == new:
        return new
    
    # Tokenize both strings
    old_tokens = _tokenize(old)
    new_tokens = _tokenize(new)
    
    # Perform diff on token sequences
    sm = SequenceMatcher(None, old_tokens, new_tokens)
    result: list[str] = []
    
    for (tag, i1, i2, j1, j2) in sm.get_opcodes():
        if tag == 'equal':
            result.extend(old_tokens[i1:i2])
        elif tag == 'replace':
            old_part = ''.join(old_tokens[i1:i2])
            new_part = ''.join(new_tokens[j1:j2])
            result.append(f'{{{old_part}→{new_part}}}')
        elif tag == 'delete':
            old_part = ''.join(old_tokens[i1:i2])
            result.append(f'{{{old_part}→}}')
        elif tag == 'insert':
            new_part = ''.join(new_tokens[j1:j2])
            result.append(f'{{→{new_part}}}')
    
    return ''.join(result)


def _tokenize(s: str) -> list[str]:
    """
    Tokenizes a string into meaningful units for diffing.
    
    Tokens:
    - Runs of letters: [a-zA-Z]+
    - Runs of digits and formatting chars: [\\d:,.]+
    - Single characters: any other character
    
    Examples:
        >>> _tokenize("hello world")
        ['hello', ' ', 'world']
        >>> _tokenize("2:18:01")
        ['2:18:01']
        >>> _tokenize("2,310 items")
        ['2,310', ' ', 'items']
    """
    tokens: list[str] = []
    i = 0
    while i < len(s):
        # Try to match a run of letters
        if s[i].isalpha():
            j = i
            while j < len(s) and s[j].isalpha():
                j += 1
            tokens.append(s[i:j])
            i = j
        # Try to match a run of digits and formatting chars
        elif s[i].isdigit() or s[i] in ':,.':
            j = i
            while j < len(s) and (s[j].isdigit() or s[j] in ':,.'):
                j += 1
            tokens.append(s[i:j])
            i = j
        # Single character token
        else:
            tokens.append(s[i])
            i += 1
    return tokens


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
T = WindowNavigator(path='T')
T.__doc__ = (
    """
    The top navigator, pointing to the root of the wx.Window hierarchy.
    
    The repr() of the top navigator provides an snapshot of all visible
    windows in the wxPython application.
    
    The children of the top navigator correspond to all visible top-level windows.
    
    # Examples
    
    Look at the entire UI:
        >>> T
    
    Look at part of the UI:
        >>> T['cr-task-tree']  # lookup by Name (focused view!)
        >>> T(Id=wx.ID_YES)  # lookup by Id
        >>> T(Label='✏️')  # lookup by Label
        >>> T[0][0][1]  # lookup by index; prefer other less-brittle methods
    
    Click a button, checkbox, or radio button:
        >>> click(T(Id=wx.ID_YES).W)
        >>> click(T(Label='Open as &read only').W)
        >>> click(T['cr-preferences-dialog__no-proxy-radio'].W)
    
    Wait for UI changes:
        >>> await wait_for(lambda: len(T['cr-task-tree'].Tree.Children) == 0)
        >>> await wait_for(lambda: T['cr-download-button'].W.IsEnabled())
    
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
