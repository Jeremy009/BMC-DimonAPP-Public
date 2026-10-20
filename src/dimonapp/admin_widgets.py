"""Streamlit building blocks shared by the tabs of the admin console."""

from typing import Optional

import sqlalchemy as sa
import streamlit as st

from dimonapp.database import open_session
from dimonapp.worker_admin import find_workers
from dimonapp.worker_types import build_worker_option

WORKER_SELECT_LABEL = 'Travailleur'
NO_WORKER_TEXT = 'Aucun travailleur enregistré.'


def render_worker_select(engine: sa.Engine, key: str) -> Optional[int]:
    """Render the dropdown of all workers; give the id of the chosen one, or None without any."""
    with open_session(engine=engine) as session:
        workers = find_workers(session=session)
        options = {worker.id: build_worker_option(worker=worker) for worker in workers}
    if not options:
        st.info(NO_WORKER_TEXT)
        return None
    return st.selectbox(
        label=WORKER_SELECT_LABEL,
        options=list(options),
        format_func=lambda worker_id: options[worker_id],
        key=key,
    )
