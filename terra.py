import os
import json
import re
from random import choice
from time import sleep, time
from datetime import datetime
from collections import namedtuple
import pickle
import click
import pandas as pd
import requests
from bs4 import BeautifulSoup
from PIL import Image
import googlemaps
import geopandas as gpd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import Select
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from shapely.geometry import Point



class Geography:
    def __init__(self, locality=False):
        """
        Geocodes a bounding box around a given community or area. the 'geography' attribute
        will hold the matrix of coordinates to pass to Spin.
        """
        self.google = googlemaps.Client(key=os.environ['GOOGLE_API_KEY'])

        if locality:
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
        if ';' in locality:
            left, right = locality.split(';')
            ll, rl = left.split(','), right.split(',')
            points_ne = [float(item) for item in ll]
            points_sw = [float(item) for item in rl]
            viewport = dict()
            viewport['northeast'] = dict()
            viewport['southwest'] = dict()
            viewport['northeast']['lat'] = points_ne[0]
            viewport['northeast']['lng'] = points_ne[1]
            viewport['southwest']['lat'] = points_sw[0]
            viewport['southwest']['lng'] = points_sw[1]
            formatted_address = 'Manual Bounds'
        else:
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
            payload['x'], payload['y'] = payload['y'], payload['x']

        url = 'http://epsg.io/trans'
        r = requests.get(url, params=payload)
        try:
            data = r.json()
        except ValueError:
            data = dict(y='0', x='0')

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
    Interface with land titles. Will return a 'dataframe' attribute with titles
    """
    def __init__(self, grid=False, pull_period=False, journal=False):
        self.runtime = time()
        self.session = self.authenticate()
        self.data = []

        if journal:
            self.journal = pd.read_pickle(journal)
            if pull_period:
                self.pull(pull_period)
        else:
            if grid:
                self.fetch(grid)
                self.bundle()
                if pull_period:
                    self.pull(pull_period)

        return None


    def authenticate(self):
        """
        Login to Spin as a guest and return the requests session
        """

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

            sleep(2)
            legal_notice_page = s.post('https://alta.registries.gov.ab.ca/SpinII/logon.aspx', \
                    data=login_payload).content
            soup = BeautifulSoup(legal_notice_page, 'html.parser')

            login_payload['__VIEWSTATE'] = soup.select_one('#__VIEWSTATE')['value']
            login_payload['cmdYES.x'] = 55
            login_payload['cmdYES.y'] = 12
            del login_payload['__EVENTARGUMENT']
            del login_payload['__EVENTTARGET']

            sleep(2)
            confirm_guest_page = s.post('https://alta.registries.gov.ab.ca/SpinII/legalnotice.aspx', \
                    data=login_payload).content
            soup = BeautifulSoup(confirm_guest_page, 'html.parser')

            if len(soup.find_all(text='You are logged on as a Guest.')) > 0:
                return s


    def fetch(self, grid):
        """
        Performs the grid searching and builds a journal dataframe with the full list of
        titles to filter and pull.
        """
        with self.session as s:
            # Recursively handle either a grid or a single bound
            if type(grid[0]) is list:
                with click.progressbar(grid, label='Fetching journal') as g:
                    for bound in g:
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

                sleep(3)
                r = s.get(url, params=payload)
                soup = BeautifulSoup(r.content, 'html.parser')

                # Extract the table and load into a DataFrame
                try:
                    table = soup.find('table', class_='bodyText')
                    df = pd.read_html(str(table), index_col=0, header=0, parse_dates=False)[0]
                    df['Registration Date'] = pd.to_datetime(df['Registration Date'], format='%d/%m/%Y')
                    df['Change/Cancel Date'] = pd.to_datetime(df['Change/Cancel Date'], format='%d/%m/%Y')

                    self.data.append(df)
                except:
                    pass


    def bundle(self):
        """
        Bundles a list of DataFrames into one and sorts by registration date
        """
        if len(self.data) > 0:
            self.journal = self.data[0].append(self.data[1:])
        self.journal = self.journal[self.journal['Type'] == 'Current Title']
        self.journal = self.journal[self.journal['Rights'] != 'Mineral']
        self.journal = self.journal[~self.journal.index.duplicated(keep='first')]
        self.journal = self.journal.sort_values(by=['Registration Date'], ascending=False)
        return self.journal


    def pull(self, period):
        """
        Takes the journal dataframe and coordinates the retrieval and parsing of individual
        tiles.
        """
        # Compile the regex expressions we'll use to parse the title text
        self.identity_regex = re.compile(r"(\d{4} \d{3} \d{3})\s{2,}(\S+)\s{2,}(\d{3} \d{3} \d{3} *\S*)")
        self.ats_regex = re.compile(r"ATS REFERENCE: (\S*)")
        self.municipality_regex = re.compile(r"MUNICIPALITY: (.*)")
        self.reference_regex = re.compile(r"REFERENCE NUMBER: (.*?)\-{80}", re.DOTALL)
        self.payday_regex = re.compile(r"(\-{80}).*(\-{80})(.*)", re.DOTALL)

        # Filter the dataframe by date and retrieve each title
        df = self.journal
        df = df[df['Registration Date'] >= period]

        df.to_pickle('run/{}.journal.pkl'.format(self.runtime))

        click.echo('Journal constructed and saved with timestamp {}'.format(self.runtime))

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
                'consideration',
                'condo'
            ], index=df.index
        )

        with click.progressbar(df.iterrows(), label='Pulling basic title data', length=len(df)) as d:
            for index, row in d:
                try:
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
                    self.dataframe.loc[index, 'condo'] = payload['condo']
                except TypeError:
                    pass

        self.dataframe['registration_date'] = pd.to_datetime(self.dataframe['registration_date'])
        self.dataframe['sworn_value'] = self.dataframe['sworn_value'].astype(float)
        self.dataframe['consideration'] = self.dataframe['consideration'].astype(float)
        self.dataframe['condo'] = self.dataframe['condo'].fillna(False).astype(bool)

        self.dataframe.to_pickle('run/{}.dataframe.pkl'.format(self.runtime))
        click.echo('Dataframe constructed and saved with timestamp {}'.format(self.runtime))

        return self.dataframe


    def retrieve_title(self, index):
        """
        Called within pull() on  an individual title number
        """
        with self.session as s:
            article_url = (
                'https://alta.registries.gov.ab.ca/SpinII'
                '/ImmediateCheckoutPreviewHTML.aspx'
                '?ArticleTypeID=f1fdd406-26aa-45d5-9bf9-3f552c972a5c'
                '&ArticleType=CurrentTitle'
                '&ArticleID=%s&NextPage=' % index
            )
            sleep(2)
            article = s.get(article_url)
            soup = BeautifulSoup(article.content, 'html.parser')
            if soup.pre:
                payload = self.parse_title(soup.pre)
                with open('data/titles/{}.txt'.format(index), "w") as f:
                    f.write(payload['title_text'])
                return payload


    def parse_title(self, pre):
        """
        Takes raw title information and parses it with regex to normalize the data.
        """
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

        if "CONDOMINIUM" in title_text:
            title['condo'] = True
        else:
            title['condo'] = False

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


class Spatial:
    """
    Enhanced data sourcing which obtains coordinates for each transaction and a screenshot
    site plan
    """
    def __init__(self, dataframe=False):
        self.runtime = time()
        self.spatial_count = 0
        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--window-size=1200,800")

        self.driver = webdriver.Chrome(chrome_options=chrome_options)

        self.driver.get('https://alta.registries.gov.ab.ca/spinii/logon.aspx')
        sleep(1)
        self.driver.find_element_by_id('uctrlLogon_cmdLogonGuest').click()
        sleep(1)
        self.driver.find_element_by_id('cmdYES').click()
        sleep(1)
        self.driver.get('http://alta.registries.gov.ab.ca/SpinII/mapindex.aspx')

        if len(dataframe) > 0:
            geoseries = self.build_geoseries(dataframe)
            self.geodataframe = gpd.GeoDataFrame(dataframe, geometry=geoseries)
            self.geodataframe.to_pickle('run/{}.geodataframe.pkl'.format(self.runtime))
            click.echo('Geodataframe constructed and saved with timestamp {}'.format(self.runtime))
            self.close()

        return None

    def build_geoseries(self, dataframe):
        """Runs map_property on a list of lincs and returns the geoseries"""
        geo_list = []
        with click.progressbar(dataframe.iterrows(), label='Pulling site plans and geographic title data', length=len(dataframe)) as d:
            for index, row in d:
                geo_list.append(self.map_property(row['linc']))

        geo_series = gpd.GeoSeries([Point(mark) for mark in geo_list], index=dataframe.index)

        return geo_series



    def map_property(self, linc):
        """Map search a linc"""
        sleep(1)
        linc = '{}'.format(linc).zfill(10)
        self.driver.switch_to_frame('fOpts')
        select_box = Select(self.driver.find_element_by_id('Finds_lstFindTypes'))
        select_box.select_by_visible_text('Linc Number')
        linc_box = self.driver.find_element_by_id('Finds_ctlLincNumber_txtLincNumber')
        linc_box.clear()
        linc_box.send_keys(linc)
        self.driver.find_element_by_id('Finds_cmdSubmit').click()
        if self.spatial_count == 0:
                sleep(8)
        sleep(4)
        self.driver.switch_to_default_content()
        if self.spatial_count == 0:
            sleep(5)
        e = WebDriverWait(self.driver, 60).until(
                EC.presence_of_element_located((By.ID, 'map'))
        )
        hover_target = self.driver.find_element_by_id('map')
        if self.spatial_count == 0:
            sleep(5)
        map_location = hover_target.location
        map_size = hover_target.size
        filename = 'data/sites/{}.png'.format(linc)
        self.driver.save_screenshot(filename)
        x = map_location['x'] + 50
        y = map_location['y']
        width = map_location['x'] + map_size['width'] - 50
        height = map_location['y'] + map_size['height']
        im = Image.open(filename)
        im = im.crop((int(x), int(y), int(width), int(height)))
        im.save(filename)
        if self.spatial_count == 0:
            sleep(5)
        ActionChains(self.driver).move_to_element(hover_target).drag_and_drop_by_offset(hover_target, 1, 1).perform()
        if self.spatial_count == 0:
            sleep(5)
        nad83_raw = self.driver.find_element_by_id('coordinateOutput').text
        nad83 = tuple(re.findall(r"[0-9\.\-]+", nad83_raw))
        gps = Geography().nad83(nad83, reverse=True)
        gpsr = (gps[1], gps[0])
        self.spatial_count += 1
        return gpsr


    def close(self):
        self.driver.quit()
        return None


@click.command()
@click.argument('community', nargs=1)
@click.option('--date', prompt=True, help='Date to pull from')
@click.option('--condo/--no-condo', default=False, help='Pass condos to Spatial')
@click.option('--journal', default=False, help='Use existing journal pickle')
@click.option('--dataframe', default=False, help='Use existing dataframe pickle')
@click.option('--save', default=False, help='Path to save GeoJSON')
@click.option('--force/--no-force', default=False, help='Silence all confirmations')
def terra(community, date, condo, journal, dataframe, save, force):
    """
    Entry point for CLI
    """
    if not dataframe:
        if not journal:
            geo = Geography(community)
            if not force: click.confirm('There are {} grids in {}. Continue?'.format(len(geo.geography), geo.bounds.locality), abort=True)

            date_object = datetime.strptime(date, '%Y-%m-%d')
            if not force: click.confirm('Journal all transactions beginning {}?'.format(date_object.strftime('%B %d, %Y')), abort=True)

            spin = Spin(geo.geography, date)
        else:
            spin = Spin(pull_period=date, journal=journal)
    else:
        spin = Spin()
        spin.dataframe = pd.read_pickle(dataframe)


    if condo:
        if not force: click.confirm('There are {} records to retrieve. Continue?'.format(len(spin.dataframe)), abort=True)
        data = Spatial(spin.dataframe)
    else:
        if not force: click.confirm('There are {} records to retrieve. Continue?'.format(len(spin.dataframe[spin.dataframe['condo'] == False])), abort=True)
        data = Spatial(spin.dataframe[spin.dataframe['condo'] == False])

    data.geodataframe['registration_date'] = data.geodataframe['registration_date'].astype(str)
    data.geodataframe['condo'] = data.geodataframe['condo'].astype(int)

    if save:
        data.geodataframe.to_file('data/geojson/{}'.format(save), driver='GeoJSON')
        click.echo('{} saved to data folder'.format(save))


if __name__ == '__main__':
    pass
