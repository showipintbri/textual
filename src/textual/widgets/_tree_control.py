from __future__ import annotations


from typing import ClassVar, Generic, Iterator, NewType, TypeVar

import rich.repr
from rich.console import RenderableType
from rich.text import Text, TextType
from rich.tree import Tree

from ..geometry import Region, Size
from .. import events
from ..reactive import Reactive
from .._types import MessageTarget
from ..widget import Widget
from ..message import Message
from .. import messages


NodeID = NewType("NodeID", int)


NodeDataType = TypeVar("NodeDataType")


@rich.repr.auto
class TreeNode(Generic[NodeDataType]):
    def __init__(
        self,
        parent: TreeNode[NodeDataType] | None,
        node_id: NodeID,
        control: TreeControl,
        tree: Tree,
        label: TextType,
        data: NodeDataType,
    ) -> None:
        self.parent = parent
        self.id = node_id
        self._control = control
        self._tree = tree
        self.label = label
        self.data = data
        self.loaded = False
        self._expanded = False
        self._empty = False
        self._tree.expanded = False
        self.children: list[TreeNode] = []

    def __rich_repr__(self) -> rich.repr.Result:
        yield "id", self.id
        yield "label", self.label
        yield "data", self.data

    @property
    def control(self) -> TreeControl:
        return self._control

    @property
    def empty(self) -> bool:
        return self._empty

    @property
    def expanded(self) -> bool:
        return self._expanded

    @property
    def is_cursor(self) -> bool:
        return self.control.cursor == self.id and self.control.show_cursor

    @property
    def tree(self) -> Tree:
        return self._tree

    @property
    def next_node(self) -> TreeNode[NodeDataType] | None:
        """The next node in the tree, or None if at the end."""

        if self.expanded and self.children:
            return self.children[0]
        else:

            sibling = self.next_sibling
            if sibling is not None:
                return sibling

            node = self
            while True:
                if node.parent is None:
                    return None
                sibling = node.parent.next_sibling
                if sibling is not None:
                    return sibling
                else:
                    node = node.parent

    @property
    def previous_node(self) -> TreeNode[NodeDataType] | None:
        """The previous node in the tree, or None if at the end."""

        sibling = self.previous_sibling
        if sibling is not None:

            def last_sibling(node) -> TreeNode[NodeDataType]:
                if node.expanded and node.children:
                    return last_sibling(node.children[-1])
                else:
                    return (
                        node.children[-1] if (node.children and node.expanded) else node
                    )

            return last_sibling(sibling)

        if self.parent is None:
            return None
        return self.parent

    @property
    def next_sibling(self) -> TreeNode[NodeDataType] | None:
        """The next sibling, or None if last sibling."""
        if self.parent is None:
            return None
        iter_siblings = iter(self.parent.children)
        try:
            for node in iter_siblings:
                if node is self:
                    return next(iter_siblings)
        except StopIteration:
            pass
        return None

    @property
    def previous_sibling(self) -> TreeNode[NodeDataType] | None:
        """Previous sibling or None if first sibling."""
        if self.parent is None:
            return None
        iter_siblings = iter(self.parent.children)
        sibling: TreeNode[NodeDataType] | None = None

        for node in iter_siblings:
            if node is self:
                return sibling
            sibling = node
        return None

    def expand(self, expanded: bool = True) -> None:
        self._expanded = expanded
        self._tree.expanded = expanded
        self._control.refresh(layout=True)

    def toggle(self) -> None:
        self.expand(not self._expanded)

    def add(self, label: TextType, data: NodeDataType) -> None:
        self._control.add(self.id, label, data=data)
        self._control.refresh(layout=True)
        self._empty = False

    def __rich__(self) -> RenderableType:
        return self._control.render_node(self)


@rich.repr.auto
class TreeClick(Generic[NodeDataType], Message, bubble=True):
    def __init__(self, sender: MessageTarget, node: TreeNode[NodeDataType]) -> None:
        self.node = node
        super().__init__(sender)

    def __rich_repr__(self) -> rich.repr.Result:
        yield "node", self.node


class TreeControl(Generic[NodeDataType], Widget, can_focus=True):
    DEFAULT_CSS = """
    TreeControl {
        background: $panel;
        color: $text-panel;
        height: auto;
        width: 100%;
    }

    TreeControl > .tree--guides {
        color: $success;
    }

    TreeControl > .tree--guides-highlight {
        color: $secondary;
        text-style: bold;
    }

    TreeControl > .tree--labels {
        color: $text-panel;
    }

    TreeControl > .tree--cursor {
        background: $secondary;
        color: $text-secondary;
    }
    
    """

    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "tree--guides",
        "tree--guides-highlight",
        "tree--labels",
        "tree--cursor",
    }

    class NodeSelected(Message, bubble=False):
        def __init__(self, sender: MessageTarget, node: TreeNode[NodeDataType]) -> None:
            self.node = node
            super().__init__(sender)

    def __init__(
        self,
        label: TextType,
        data: NodeDataType,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self.data = data

        self.node_id = NodeID(0)
        self.nodes: dict[NodeID, TreeNode[NodeDataType]] = {}
        self._tree = Tree(label)

        self.root: TreeNode[NodeDataType] = TreeNode(
            None, self.node_id, self, self._tree, label, data
        )

        self._tree.label = self.root
        self.nodes[NodeID(self.node_id)] = self.root
        super().__init__(name=name, id=id, classes=classes)

    hover_node: Reactive[NodeID | None] = Reactive(None)
    cursor: Reactive[NodeID] = Reactive(NodeID(0))
    cursor_line: Reactive[int] = Reactive(0)
    show_cursor: Reactive[bool] = Reactive(False)

    def watch_show_cursor(self, value: bool) -> None:
        line_region = Region(0, self.cursor_line, self.size.width, 1)
        self.emit_no_wait(messages.ScrollToRegion(self, line_region))

    def watch_cursor_line(self, value: int) -> None:
        line_region = Region(0, value, self.size.width, 1)
        self.emit_no_wait(messages.ScrollToRegion(self, line_region))

    def watch_hover_node(self, previous_hover_node: NodeID, hover_node: NodeID) -> None:
        previous_hover = self.nodes.get(previous_hover_node)
        if previous_hover is not None:
            previous_hover._tree.guide_style = self._guide_style
        hover = self.nodes.get(hover_node)
        if hover is not None:
            hover._tree.guide_style = self._highlight_guide_style
        self.refresh()

    def watch_cursor(self, previous_cursor_node: NodeID, cursor_node: NodeID) -> None:

        previous_cursor = self.nodes.get(previous_cursor_node)
        if previous_cursor is not None:
            previous_cursor._tree.guide_style = self._guide_style
        cursor = self.nodes.get(cursor_node)
        if cursor is not None:
            cursor._tree.guide_style = self._highlight_guide_style
        self.refresh()

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        def get_size(tree: Tree) -> int:
            return 1 + sum(
                get_size(child) if child.expanded else 1 for child in tree.children
            )

        size = get_size(self._tree)
        return size

    def add(
        self,
        node_id: NodeID,
        label: TextType,
        data: NodeDataType,
    ) -> None:

        parent = self.nodes[node_id]
        self.node_id = NodeID(self.node_id + 1)
        child_tree = parent._tree.add(label)
        child_tree.guide_style = self._guide_style
        child_node: TreeNode[NodeDataType] = TreeNode(
            parent, self.node_id, self, child_tree, label, data
        )
        parent.children.append(child_node)
        child_tree.label = child_node
        self.nodes[self.node_id] = child_node

        self.refresh(layout=True)

    def find_cursor(self) -> int | None:
        """Find the line location for the cursor node."""

        node_id = self.cursor
        line = 0

        stack: list[Iterator[TreeNode[NodeDataType]]]
        stack = [iter([self.root])]

        pop = stack.pop
        push = stack.append
        while stack:
            iter_children = pop()
            try:
                node = next(iter_children)
            except StopIteration:
                continue
            else:
                if node.id == node_id:
                    return line
                line += 1
                push(iter_children)
                if node.children and node.expanded:
                    push(iter(node.children))
        return None

    def render(self) -> RenderableType:
        return self._tree

    def render_node(self, node: TreeNode[NodeDataType]) -> RenderableType:
        label_style = self.get_component_styles("tree--labels").rich_style
        label = (
            Text(node.label, no_wrap=True, style=label_style, overflow="ellipsis")
            if isinstance(node.label, str)
            else node.label
        )
        if node.id == self.hover_node:
            label.stylize("underline")
        label.apply_meta({"@click": f"click_label({node.id})", "tree_node": node.id})
        return label

    def action_click_label(self, node_id: NodeID) -> None:
        node = self.nodes[node_id]
        self.cursor = node.id
        self.cursor_line = self.find_cursor() or 0
        self.show_cursor = True
        self.post_message_no_wait(self.NodeSelected(self, node))

    def on_mount(self) -> None:
        self._guide_style = self.get_component_styles("tree--guides").rich_style
        self._highlight_guide_style = self.get_component_styles(
            "tree--guides-highlight"
        ).rich_style
        self._tree.guide_style = self._guide_style

    def on_mouse_move(self, event: events.MouseMove) -> None:
        self.hover_node = event.style.meta.get("tree_node")

    async def on_key(self, event: events.Key) -> None:
        await self.dispatch_key(event)

    def key_down(self, event: events.Key) -> None:
        event.stop()
        self.cursor_down()

    def key_up(self, event: events.Key) -> None:
        event.stop()
        self.cursor_up()

    def key_pagedown(self) -> None:
        assert self.parent is not None
        height = self.container_viewport.height

        cursor = self.cursor
        cursor_line = self.cursor_line
        for _ in range(height):
            cursor_node = self.nodes[cursor]
            next_node = cursor_node.next_node
            if next_node is not None:
                cursor_line += 1
                cursor = next_node.id
        self.cursor = cursor
        self.cursor_line = cursor_line

    def key_pageup(self) -> None:
        assert self.parent is not None
        height = self.container_viewport.height
        cursor = self.cursor
        cursor_line = self.cursor_line
        for _ in range(height):
            cursor_node = self.nodes[cursor]
            previous_node = cursor_node.previous_node
            if previous_node is not None:
                cursor_line -= 1
                cursor = previous_node.id
        self.cursor = cursor
        self.cursor_line = cursor_line

    def key_home(self) -> None:
        self.cursor_line = 0
        self.cursor = NodeID(0)

    def key_end(self) -> None:
        self.cursor = self.nodes[NodeID(0)].children[-1].id
        self.cursor_line = self.find_cursor() or 0

    def key_enter(self, event: events.Key) -> None:
        cursor_node = self.nodes[self.cursor]
        event.stop()
        self.post_message_no_wait(self.NodeSelected(self, cursor_node))

    def cursor_down(self) -> None:
        if not self.show_cursor:
            self.show_cursor = True
            return
        cursor_node = self.nodes[self.cursor]
        next_node = cursor_node.next_node
        if next_node is not None:
            self.cursor_line += 1
            self.cursor = next_node.id

    def cursor_up(self) -> None:
        if not self.show_cursor:
            self.show_cursor = True
            return
        cursor_node = self.nodes[self.cursor]
        previous_node = cursor_node.previous_node
        if previous_node is not None:
            self.cursor_line -= 1
            self.cursor = previous_node.id
