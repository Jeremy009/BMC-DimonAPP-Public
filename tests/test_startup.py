"""Container start-up command."""

from dimonapp.startup import APP_PATH, build_streamlit_command


def test_r1_6_streamlit_is_served_on_the_given_port() -> None:
    """Streamlit runs the application headless on every interface, on the injected port."""
    command = build_streamlit_command(port=8080)

    assert command[:3] == ['streamlit', 'run', str(APP_PATH)]
    assert '--server.port=8080' in command
    assert '--server.address=0.0.0.0' in command
    assert '--server.headless=true' in command
    assert APP_PATH.is_file()
