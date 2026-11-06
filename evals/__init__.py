"""Prompt scoring for the contextual menu.

Kept out of `backend/` on purpose. This is a *development* tool: it calls a model, costs
money or minutes, and asserts nothing that belongs in `pytest`. `backend/` must not import
it, and nothing the app serves may depend on it.

The point is that a prompt change is otherwise unmeasurable - the only feedback is reading
one answer and forming an impression, which is how a prompt gets worse over time and no one
notices.
"""
