import os
import json
import re
from random import choice
from time import sleep, time
from collections import namedtuple
import pickle
import click
import pandas as pd
import requests
from bs4 import BeautifulSoup
import googlemaps


class Geography:
    def __init__(self, locality):
        self.google = googlemaps.Client(key=os.environ['GOOGLE_API_KEY'])

        self.bounds = self.bound(locality)
        self.northeast, self.southwest = self.nad83(self.bounds.northeast), self.nad83(self.bounds.southwest)
        self.geography = self.grid(self.northeast, self.southwest)

        return None


    def bound(self, locality, province='Alberta', country='Canada'):
        """
        Returns a GPS named tuple with resolved address and bound coordinates using
        Google's googlemaps API. GOOGLE_API_KEY must be set in Environment Variables.
        """
        filters = {
            'administrative_area': province,
            'country': country
        }
        result = self.google.geocode(locality, components=filters)[0]

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


    def nad83(self, coordinates, reverse=False):
        """
        Uses the EPSG API to convert GPS coordinate tuple to Alberta 10-TM Forest coordinates
        """
        payload = {
            'format': 'json',
            's_srs': 4326,
            't_srs': 3401,
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


    def grid(self, northeast, southwest, density=500):
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
    def __init__(self, grid=False, pull_period=False):
        self.runtime = time()
        self.session = self.authenticate()
        self.data = []

        if grid:
            self.fetch(grid)
            self.bundle()
            if pull_period:
                self.pull(pull_period)

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

            sleep(3)
            legal_notice_page = s.post('https://alta.registries.gov.ab.ca/SpinII/logon.aspx', \
                    data=login_payload).content
            soup = BeautifulSoup(legal_notice_page, 'html.parser')

            login_payload['__VIEWSTATE'] = soup.select_one('#__VIEWSTATE')['value']
            login_payload['cmdYES.x'] = 55
            login_payload['cmdYES.y'] = 12
            del login_payload['__EVENTARGUMENT']
            del login_payload['__EVENTTARGET']

            sleep(3)
            confirm_guest_page = s.post('https://alta.registries.gov.ab.ca/SpinII/legalnotice.aspx', \
                    data=login_payload).content
            soup = BeautifulSoup(confirm_guest_page, 'html.parser')

            if len(soup.find_all(text='You are logged on as a Guest.')) > 0:
                return s


    def fetch(self, grid):
        with self.session as s:
            # Recursively handle either a grid or a single bound
            if type(grid[0]) is list:
                for bound in grid:
                    self.fetch(bound)
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

                sleep(10)
                r = s.get(url, params=payload)
                soup = BeautifulSoup(r.content, 'html.parser')

                # Extract the table and load into a DataFrame
                table = soup.find('table', class_='bodyText')
                df = pd.read_html(str(table), index_col=0, header=0, parse_dates=False)[0]
                df['Registration Date'] = pd.to_datetime(df['Registration Date'], format='%d/%m/%Y')
                df['Change/Cancel Date'] = pd.to_datetime(df['Change/Cancel Date'], format='%d/%m/%Y')

                self.data.append(df)


    def bundle(self):
        self.journal = self.data[0].append(self.data[1:])
        self.journal = self.journal.drop_duplicates()
        self.journal = self.journal.sort_values(by=['Registration Date'], ascending=False)
        return self.journal


    def pull(self, period):
        # Compile the regex expressions we'll use to parse the title text
        self.identity_regex = re.compile(r"(\d{4} \d{3} \d{3})\s{2,}(\S+)\s{2,}(\d{3} \d{3} \d{3} *\S*)")
        self.ats_regex = re.compile(r"ATS REFERENCE: (\S*)")
        self.municipality_regex = re.compile(r"MUNICIPALITY: (.*)")
        self.reference_regex = re.compile(r"REFERENCE NUMBER: (.*?)\-{80}", re.DOTALL)
        self.payday_regex = re.compile(r"(\-{80}).*(\-{80})(.*)", re.DOTALL)

        # Filter the dataframe by date and retrieve each title
        df = self.journal
        df = df[df['Registration Date'] >= period]

        print(len(df))
        df.to_pickle('{}.journal.pkl'.format(self.runtime))

        # Set up structure for target DataFrame
        self.dataframe = pd.DataFrame(
            columns=[
                'linc',
                'short_legal',
                'title_number',
                'ats_reference',
                'municipality',
                'registration',
                'registration_date',
                'document_type',
                'sworn_value',
                'consideration'
            ], index=df.index
        )

        for index, row in df.iterrows():
            payload = self.retrieve_title(index)
            self.dataframe.loc[index, 'linc'] = payload['linc']
            self.dataframe.loc[index, 'short_legal'] = payload['short_legal']
            self.dataframe.loc[index, 'title_number'] = payload['title_number']
            self.dataframe.loc[index, 'ats_reference'] = payload['ats_reference']
            self.dataframe.loc[index, 'municipality'] = payload['municipality']
            self.dataframe.loc[index, 'registration'] = payload['registration']
            self.dataframe.loc[index, 'registration_date'] = payload['date']
            self.dataframe.loc[index, 'document_type'] = payload['document_type']
            self.dataframe.loc[index, 'sworn_value'] = payload['value']
            self.dataframe.loc[index, 'consideration'] = payload['consideration']

        self.dataframe['linc'] = self.dataframe['linc'].astype(int)
        self.dataframe['registration_date'] = pd.to_datetime(self.dataframe['registration_date'])
        self.dataframe['sworn_value'] = self.dataframe['sworn_value'].astype(float)
        self.dataframe['consideration'] = self.dataframe['consideration'].astype(float)

        self.dataframe.to_pickle('{}.dataframe.pkl'.format(self.runtime))

        return self.dataframe


    def retrieve_title(self, index):
        with self.session as s:
            article_url = (
                'https://alta.registries.gov.ab.ca/SpinII'
                '/ImmediateCheckoutPreviewHTML.aspx'
                '?ArticleTypeID=f1fdd406-26aa-45d5-9bf9-3f552c972a5c'
                '&ArticleType=CurrentTitle'
                '&ArticleID=%s&NextPage=' % index
            )
            sleep(3)
            article = s.get(article_url)
            soup = BeautifulSoup(article.content, 'html.parser')
            if soup.pre:
                payload = self.parse_title(soup.pre)
                return payload


    def parse_title(self, pre):
        # Extract datapoints
        title_text = str(pre)
        title = {}

        identity_data = self.identity_regex.search(title_text)
        title['linc'] = int(identity_data.group(1).strip().replace(' ', ''))
        title['short_legal'] = identity_data.group(2).strip().replace(';', ' ')
        title['title_number'] = identity_data.group(3).strip()

        try:
            title['ats_reference'] = self.ats_regex.search(title_text).group(1).replace(';',' ')
        except AttributeError:
            title['ats_reference'] = ''

        title['municipality'] = self.municipality_regex.search(title_text).group(1).replace('\r','')

        try:
            references = self.reference_regex.search(title_text).group(1).split("\n")
            references = [i.strip() for i in references]
            references = list(filter(None, references))
            title['reference_number'] = references
        except AttributeError:
            title['reference_number'] = ['']

        payday_raw = self.payday_regex.search(title_text).group(3).strip('</pre>').strip()
        title['registration'] = payday_raw[:11]
        title['date'] = reversed(payday_raw[15:25].split('/'))
        title['date'] = '-'.join(title['date'])
        title['document_type'] = payday_raw[27:46].strip()

        title['value'] = self._try_int(payday_raw[46:62].strip())
        title['consideration'] = self._try_int(payday_raw[62:80].strip())

        title['title_text'] = title_text.strip('<pre>').strip('</pre>').strip()

        return title


    def _try_int(self, string):
        """Try to convert a string to integer; return None if non-numeric"""
        value = re.sub(r"[^0-9]+", '', string)
        try:
            value = int(value)
        except ValueError:
            value = None
        return value


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
