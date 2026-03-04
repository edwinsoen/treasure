from app.audit.context import AuditContext


class TestAuditContext:
    def test_defaults(self) -> None:
        ctx = AuditContext()
        assert ctx.actor == ""
        assert ctx.action is None
        assert ctx.entity_type is None
        assert ctx.changes is None
        assert ctx.params is None

    def test_is_mutable(self) -> None:
        ctx = AuditContext()
        ctx.actor = "507f1f77bcf86cd799439011"
        ctx.action = "create"
        ctx.entity_type = "account"
        ctx.changes = {"name": {"old": None, "new": "Chase"}}
        ctx.params = {"name": "Chase"}
        assert ctx.actor == "507f1f77bcf86cd799439011"
        assert ctx.action == "create"
        assert ctx.entity_type == "account"
        assert ctx.changes == {"name": {"old": None, "new": "Chase"}}
        assert ctx.params == {"name": "Chase"}
