"""Take the README screenshots of a running DimonAPP (see take-screenshots.sh).

Usage: python take_screenshots.py <application address> <output folder> <worker password>
"""

import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

WIDTH = 1400
MIN_HEIGHT = 900


def wait_until_idle(page: Page) -> None:
    """Wait until Streamlit has finished running the script and drawing the page."""
    page.wait_for_timeout(1000)
    page.locator('[data-testid="stStatusWidget"]').wait_for(state='hidden', timeout=30000)
    page.wait_for_timeout(1500)


def shoot(page: Page, path: Path) -> None:
    """Grow the window to the height of the page, so nothing scrolls, and take the picture."""
    height = page.evaluate(
        'Math.max(...[...document.querySelectorAll(\'[data-testid="stMain"] *\')]'
        '.map(e => e.scrollHeight))'
    )
    page.set_viewport_size({'width': WIDTH, 'height': max(MIN_HEIGHT, height + 60)})
    page.wait_for_timeout(500)
    page.screenshot(path=str(path))
    page.set_viewport_size({'width': WIDTH, 'height': MIN_HEIGHT})


def open_tab(page: Page, name: str) -> None:
    """Click a tab by its French name."""
    page.get_by_role('tab', name=name, exact=True).click()
    wait_until_idle(page)


def main() -> None:
    """Take the login, worker and admin screenshots."""
    address, output, password = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(
            viewport={'width': WIDTH, 'height': MIN_HEIGHT},
            device_scale_factor=2,
            locale='fr-BE',
        )

        # Login page, then a local worker (article 17)
        page.goto(address)
        page.get_by_role('button', name='Se connecter', exact=True).wait_for(timeout=60000)
        wait_until_idle(page)
        shoot(page=page, path=output / '01-login.png')
        page.get_by_label("Nom d'utilisateur").fill('noor')
        page.get_by_label('Mot de passe').fill(password)
        page.get_by_role('button', name='Se connecter', exact=True).click()
        page.get_by_role('tab').first.wait_for(timeout=30000)
        wait_until_idle(page)
        shoot(page=page, path=output / '02-worker-declare.png')
        open_tab(page=page, name='Aperçu mensuel')
        shoot(page=page, path=output / '03-worker-overview.png')

        # Admin console, signed in by shots_app.py
        page.goto(f'{address}/?as=admin')
        page.get_by_role('tab').first.wait_for(timeout=30000)
        wait_until_idle(page)
        shoot(page=page, path=output / '04-admin-dashboard.png')
        open_tab(page=page, name='Rapport mensuel')
        shoot(page=page, path=output / '05-admin-report.png')
        open_tab(page=page, name='Activités')
        shoot(page=page, path=output / '06-admin-activities.png')
        open_tab(page=page, name='Travailleurs')
        shoot(page=page, path=output / '07-admin-workers.png')
        browser.close()


if __name__ == '__main__':
    main()
