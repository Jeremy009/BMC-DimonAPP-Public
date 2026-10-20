"""The action button that is disabled while its action runs (R7.3, R7.9).

Without it, every click made while a declaration or a cancellation waited on the Dimona
service queued one more run, which repeated the action.
"""

from streamlit.testing.v1 import AppTest

# A page with one action button whose action counts how often it ran. A late click from
# before the disabled button reached the browser is simulated by calling the click handler
# with the token that button was drawn with, as Streamlit does before the run. A run without
# anybody signed in drops the pending actions, as the login page does.
ACTION_PAGE = """
import streamlit as st

from dimonapp.widgets import forget_action_requests, render_action_button, request_action

if st.session_state.pop('late_click', False):
    request_action(key='go', token=0)
if st.session_state.pop('signed_out', False):
    forget_action_requests()
if render_action_button(label='Go', key='go'):
    st.session_state['n_actions'] = st.session_state.get('n_actions', 0) + 1
"""


def run_action_page() -> AppTest:
    """Run the page with the action button once, before any click."""
    app = AppTest.from_string(ACTION_PAGE)
    app.run()
    assert not app.exception
    return app


def click_go(app: AppTest) -> AppTest:
    """Click the enabled action button and run the page again."""
    app.button(key='go').click()
    app.run()
    assert not app.exception
    return app


def read_go_button_states(app: AppTest) -> list[bool]:
    """Give whether each button labelled Go on the page is disabled."""
    return [button.disabled for button in app.button if button.label == 'Go']


def test_action_button_is_disabled_while_its_action_runs() -> None:
    """The run started by the click draws the button disabled and runs the action once."""
    app = click_go(app=run_action_page())

    assert read_go_button_states(app=app) == [True]
    assert app.session_state['n_actions'] == 1


def test_action_button_is_enabled_again_on_the_next_run() -> None:
    """After the action the button can be clicked again, and each click acts once more."""
    app = click_go(app=run_action_page())
    app.run()

    assert read_go_button_states(app=app) == [False]
    click_go(app=app)
    assert app.session_state['n_actions'] == 2


def test_late_click_does_not_repeat_the_action() -> None:
    """A click sent before the disabled button arrived reruns the page but does not act."""
    app = click_go(app=run_action_page())
    app.session_state['late_click'] = True
    app.run()

    assert not app.exception
    assert read_go_button_states(app=app) == [False]
    assert app.session_state['n_actions'] == 1


def test_r4_13_click_that_arrives_while_signed_out_never_acts() -> None:
    """An action asked for in a run without anybody signed in is dropped, then and later."""
    app = run_action_page()
    app.session_state['signed_out'] = True
    click_go(app=app)
    app.run()

    assert not app.exception
    assert read_go_button_states(app=app) == [False]
    assert 'n_actions' not in app.session_state


def test_action_button_without_click_does_not_act() -> None:
    """Drawing the page alone never runs the action."""
    app = run_action_page()
    app.run()

    assert read_go_button_states(app=app) == [False]
    assert 'n_actions' not in app.session_state
