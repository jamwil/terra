import os
import json
from random import choice
from time import sleep
from collections import namedtuple
import click
import pandas as pd
import requests
from bs4 import BeautifulSoup
import googlemaps


google = googlemaps.Client(key=os.environ['GOOGLE_API_KEY'])


def bound(locality, province='Alberta', country='Canada'):
    """
    Returns a GPS named tuple with resolved address and bound coordinates using
    Google's googlemaps API. GOOGLE_API_KEY must be set in Environment Variables.
    """
    filters = {
        'administrative_area': province,
        'country': country
    }
    result = google.geocode(locality, components=filters)[0]

    formatted_address = result['formatted_address']
    viewport = result['geometry']['viewport']

    northeast = (viewport['northeast']['lat'], viewport['northeast']['lng'])
    southwest = (viewport['southwest']['lat'], viewport['southwest']['lng'])
    northwest = (viewport['northeast']['lat'], viewport['southwest']['lng'])
    southeast = (viewport['southwest']['lat'], viewport['northeast']['lng'])

    GPS = namedtuple('GPS', 'locality northeast southeast southwest northwest')
    value = GPS(locality = formatted_address, \
                northeast = northeast, southwest = southwest, \
                northwest = northwest, southeast = southeast)
    return value


def nad83(coordinates, reverse=False):
    """
    Uses the EPSG API to convert GPS coordinate tuple to Alberta 10-TM Forest coordinates
    """
    payload = {
        'format': 'json',
        's_srs': 4326,
        't_srs': 3403,
        'x': coordinates[1],
        'y': coordinates[0]
    }
    if reverse:
        payload['s_srs'], payload['t_srs'] = payload['t_srs'], payload['s_srs']

    url = 'http://epsg.io/trans'
    r = requests.get(url, params=payload)
    data = r.json()

    value = (float(data['y']), float(data['x']))
    return value


def grid(northeast, southwest, density=500):
    """
    Break a bounding box into a mesh for some grid searchin'
    """
    grid = []

    # Determine the bounds of a standard, positive quadrant plot
    y_max, y_min = int(northeast[0]), int(southwest[0])
    x_max, x_min = int(northeast[1]), int(southwest[1])

    # Construct a sequence of boxes each moving clockwise from southwest corner
    master = []
    for x in range(x_min, x_max, density):
        for y in range(y_min, y_max, density):
            polygon = [
                (x, y),
                (x, y + density),
                (x + density, y + density),
                (x + density, y),
                (x, y)
            ]
            master.append(polygon)

    return master


class Spin:
    """
    Interface with land titles
    """
    def __init__(self, grid=False):
        self.session = self.authenticate()
        self.data = []

        if grid:
            self.pull(grid)
            self.bundle()

        return None


    def authenticate(self):
        """Login to Spin as a guest and return the requests session"""

        # Choose a random user agent string from the most popular
        agent_strings = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.113 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/44.0.2403.157 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.90 Safari/537.36'
        ]
        headers = {'User-Agent': choice(agent_strings)}

        # Spin up a requests session
        with requests.Session() as s:
            s.headers.update(headers)

            login_page = s.get('https://alta.registries.gov.ab.ca/SpinII/').content
            soup = BeautifulSoup(login_page, 'html.parser')

            login_payload = {
                'uctrlFullHeader:ShutdownAlert1:Hidden1':'',
                'uctrlFullHeader:ShutdownAlert1:Hidden2':'',
                'JavascriptEnabled':1,
                'uctrlLogon:txtLogonName':'',
                'uctrlLogon:txtPassword':'',
                'uctrlLogon:cmdLogonGuest.x':59,
                'uctrlLogon:cmdLogonGuest.y':26
            }
            login_payload['__EVENTTARGET'] = soup.select_one('#__EVENTTARGET')['value']
            login_payload['__EVENTARGUMENT'] = soup.select_one('#__EVENTARGUMENT')['value']
            login_payload['__VIEWSTATE'] = soup.select_one('#__VIEWSTATE')['value']

            sleep(5)
            legal_notice_page = s.post('https://alta.registries.gov.ab.ca/SpinII/logon.aspx', \
                    data=login_payload).content
            soup = BeautifulSoup(legal_notice_page, 'html.parser')

            login_payload['__VIEWSTATE'] = soup.select_one('#__VIEWSTATE')['value']
            login_payload['cmdYES.x'] = 55
            login_payload['cmdYES.y'] = 12
            del login_payload['__EVENTARGUMENT']
            del login_payload['__EVENTTARGET']

            sleep(5)
            confirm_guest_page = s.post('https://alta.registries.gov.ab.ca/SpinII/legalnotice.aspx', \
                    data=login_payload).content
            soup = BeautifulSoup(confirm_guest_page, 'html.parser')

            if len(soup.find_all(text='You are logged on as a Guest.')) > 0:
                return s


    def pull(self, grid):
        with self.session as s:
            # Recursively handle either a grid or a single bound
            if type(grid[0]) is list:
                for bound in grid:
                    self.pull(bound)
            elif type(grid[0]) is tuple:
                # Construct the web request from the coordinates
                poly = ''.join(['{};{};'.format(point[0], point[1]) for point in grid])
                payload = {
                    'qt': 'spatial',
                    'pts': poly,
                    'rad': 0,
                    'rights': 'B'
                }
                url = 'https://alta.registries.gov.ab.ca/SpinII/SearchTitlePrint.aspx'

                sleep(5)
                r = s.get(url, params=payload)
                soup = BeautifulSoup(r.content, 'html.parser')

                table = soup.find('table', class_='bodyText')
                df = pd.read_html(str(table), index_col=0, header=0, parse_dates=False)[0]
                df['Registration Date'] = pd.to_datetime(df['Registration Date'], format='%d/%m/%Y')
                df['Change/Cancel Date'] = pd.to_datetime(df['Change/Cancel Date'], format='%d/%m/%Y')

                self.data.append(df)


    def bundle(self):
        self.dataframe = self.data[0].append(self.data[1:])
        self.dataframe = self.dataframe.drop_duplicates()
        self.dataframe = self.dataframe.sort_values(by=['Registration Date'], ascending=False)
        return self.dataframe



@click.command()
@click.argument('communities', nargs=-1)
def terra(communities):
    """
    Entry point for CLI
    """
    for community in communities:
        geocode_result = bound(community)
        ne, sw = nad83(geocode_result.northeast), nad83(geocode_result.southwest)
        grid(ne, sw)

if __name__ == '__main__':
    pass
