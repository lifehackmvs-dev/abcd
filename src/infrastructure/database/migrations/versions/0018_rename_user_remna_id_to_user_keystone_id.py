from typing import Sequence, Union

from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('subscriptions', 'user_remna_id', new_column_name='user_keystone_id')


def downgrade() -> None:
    op.alter_column('subscriptions', 'user_keystone_id', new_column_name='user_remna_id')
