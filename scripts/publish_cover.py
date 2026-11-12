#!/usr/bin/env python3
"""Render the hand-authored SVG for podcast clients and attach its PNG to both feeds."""
from pathlib import Path
import xml.etree.ElementTree as ET
import cairosvg

root=Path(__file__).resolve().parents[1]
source=root/'docs/assets/escape-pod-cover.svg'
target=root/'docs/assets/escape-pod-cover.png'
cairosvg.svg2png(url=str(source),write_to=str(target),output_width=1400,output_height=1400)
namespace='http://www.itunes.com/dtds/podcast-1.0.dtd'
ET.register_namespace('itunes',namespace)
image_url='https://udeudeude.github.io/Escape-Pod-Cast/assets/escape-pod-cover.png'
for feed in [root/'docs/feed.xml',*sorted((root/'docs/feeds').glob('*/feed.xml'))]:
    tree=ET.parse(feed)
    channel=tree.getroot().find('channel')
    if channel is None: raise ValueError('No channel in '+str(feed))
    image=channel.find('{'+namespace+'}image')
    if image is None: image=ET.SubElement(channel,'{'+namespace+'}image')
    image.set('href',image_url)
    tree.write(feed,encoding='utf-8',xml_declaration=True)
print('Rendered cover and updated podcast artwork references')
