"""Open the authorized portal with the Playwright Inspector on the local machine."""
import argparse
from threading import Event

from playwright.sync_api import Error

from .browser import Browser, URLS


def main():
    parser = argparse.ArgumentParser(description='Inspecione controles de um portal autorizado')
    parser.add_argument('portal', choices=URLS)
    args = parser.parse_args()
    browser = Browser(Event())
    try:
        browser.inspect(args.portal)
    except Error:
        parser.exit(1, 'O Chromium ou o portal não pôde ser aberto.\n')
    finally:
        browser.close()


if __name__ == '__main__':
    main()
