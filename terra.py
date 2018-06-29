import os
import json
from collections import namedtuple
import click
import numpy as np
import requests
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
        't_srs': 3402,
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
                (x + density, y)
            ]
            master.append(polygon)

    return master


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
