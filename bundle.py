import click
import os
from time import time
import json
import zipfile
import boto3

@click.command()
@click.argument('geojson_list', nargs=-1)
@click.option('--s3/--no-s3', help='Upload to Amazon S3', default=True)
def main(geojson_list, s3):
    timestamp = time()

    with zipfile.ZipFile('data/bundles/{}.zip'.format(timestamp), "w") as zip:
        click.echo('Bundling to {}.zip'.format(timestamp))

        for locality in geojson_list:
            with open('data/geojson/{}'.format(locality), "r") as geojson_file:
                j = json.load(geojson_file)
                titles = [(f['properties']['title_number'], f['properties']['linc'])
                                                            for f in j['features']]

                for title, site in titles:
                    title_file = title.replace(' ', '') + '.txt'
                    site_file = str(site).zfill(10) + '.png'

                    zip.write('data/titles/{}'.format(title_file))
                    zip.write('data/sites/{}'.format(site_file))

                zip.write('data/geojson/{}'.format(locality))

    if s3:
        s3 = boto3.resource('s3')
        s3.meta.client.upload_file('data/bundles/{}.zip'.format(timestamp), 'terra-alberta', '{}-{}.zip'.format(locality.replace('.geojson', ''), timestamp), ExtraArgs={'ACL':'public-read'})

        link = 'https://s3.ca-central-1.amazonaws.com/terra-alberta/' + '{}-{}.zip'.format(locality.replace('.geojson', ''), timestamp)
        click.echo(link)


if __name__ == '__main__':
    pass
