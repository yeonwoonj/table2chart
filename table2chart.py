#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import math
import codecs

import logging
import email

from BeautifulSoup import BeautifulSoup

from google.appengine.ext import webapp
from google.appengine.ext.webapp.mail_handlers import InboundMailHandler
from google.appengine.ext.webapp.util import run_wsgi_app

from google.appengine.api import mail
from google.appengine.api import urlfetch


def extract_number_dot(s):
    """extract number and dot(.) character from a given string"""
    return ''.join(re.findall('[0-9\.]+', s))

def extract_number_dot_dash(s):
    """extract number and dot(.) and dash(-) character from a given string"""
    return ''.join(re.findall('[0-9\.\-]+', s))

def remove_nbsp_and_strip(s):
    """remove &nbsp; and strip"""
    return s.replace('&nbsp;','').strip()

def is_value_table(rows):

    if not rows:
        return False

    if len(rows) < 2:
        return False

    if len(rows[0]) < 5:
        # assume if # of cols under 5, u don't need a graph for it.
        return False

    return True

def analyze_tbody(tbody):
    """remove unmeaningful rows and guessing header ...
    """
    rows = []

    trs = tbody.findChildren('tr')
    for tr in trs:
        tds = tr.findChildren('td')

        # the following code could not be passed the turkish test due to dot(.).
        # but, how can i fix it?
        rows.append([ extract_number_dot_dash(td.getText()) or remove_nbsp_and_strip(td.getText())
                      for td in tds ])

    if rows:
        # remove invalid rows
        longest = sorted([ len(row) for row in rows ], reverse=True)[0]
        toleration = 3
        len_limit = longest - toleration

        rows = [ row
                 for row in rows
                 if len(row) >= len_limit ]


    if is_value_table(rows):

        # distinguish head and data part
        head = rows[0]
        rows = rows[1:]

        # normalize value to represent within 100%
        def numeric_string_max(seq):
            return max([ float(extract_number_dot(s))
                         for s in seq
                         if extract_number_dot(s) ])
        
        tallest = max([ numeric_string_max(row) for row in rows ])
        tallest = str(int(math.floor(float(tallest))))
        upscale = (10**len(tallest[1:])) * (int(tallest[0]) + 1)
        if upscale < 100:
            upscale = 100

        multiplier = 100.0/upscale
        #logging.info('%s,%s'%(tallest,upscale))

        for i in range(len(rows)):
            rows[i] = rows[i][:1] + map(lambda y: str(float(y)*multiplier), rows[i][1:])

        return (head, rows, upscale)


def prune(data, max_data_size=8):
    """prune data length to up to max_data.
    the size of new data could be 6-8 (when max_data_size is 8).
    """

    data_size = len(data)

    if data_size <= max_data_size:
        return data

    k = max_data_size - 2
    v = (data_size - 2) / float(k+1)
    indices = [ int(math.ceil(v*i)) for i in range(1,k+1) ]

    # always preserve first and last elems.
    return data[:1] + [ data[i] for i in indices ] + data[-1:]


def create_chart_url(data, title=''):
    if not data:
        return

    head,rows,upscale = data

    if not rows or len(rows) < 2:
        return

    width = 800
    height = 350
    url_params = []

    # 라인 컬러
    colors_preset = ['3072F3','FF0000','307203','FF00FF']*5
    colors_text = ','.join(colors_preset[:len(rows)])

    url_params.append(u'chco=' + colors_text)

    # 데이터
    values = '|'.join([ ','.join(row[1:])
                        for row in rows ])
    url_params.append(u'chd=t:' + values)

    # 범례(legend)
    legend = '|'.join([ row[0]
                        for row in rows])

    url_params.append(u'chdl=' + legend)

    # axis label
    labels = '|'.join(prune(head[1:]))
    url_params.append(u'chxl=0:|' + labels)

    # axis label style
    url_params.append(u'chxs=0,,12,-1,lt')

    # axis range
    url_params.append(u'chxr=1,0,%d' % upscale)

    # 채우기 색
    fill = '' #u'&chm=B,3072F380,0,0,0|B,FF000060,1,0,0'

    # 제목
    if title:
        url_params.append(u'chtt=' + title)

    # 주소 만들기
    url_base = u'http://chart.apis.google.com/chart?cht=lc&chxt=x,y&chs=%dx%d&' % (width,height)

    return url_base + '&'.join(url_params)


def get_graph_urls(soup, tag='tbody'):
    
    tbodies = soup.findAll(tag)
    if not tbodies:
        return None

    urls = []
    for tbody in tbodies:

        sub_result = get_graph_urls(tbody)
        if sub_result:
            urls.extend(sub_result)
        else:
            res = analyze_tbody(tbody)
            url = create_chart_url(res)

            if url:
                urls.append(url)

    return urls


class Table2ChartHandler(InboundMailHandler):

    def loadChart(self, url):

        try:
            res = urlfetch.fetch(url)
            if res.status_code == 200:
                return res.content
        except Exception:
            time.sleep(5)
            return self.loadChart(url)

    def receive(self, mail_message):
        
        logging.info('Received a message from: ' + mail_message.sender)

        content = ''

        html_bodies = mail_message.bodies('text/html')
        for ct, body in html_bodies:
            content = body.decode()

        soup = BeautifulSoup(content)
        urls = get_graph_urls(soup)

        atts = []
        count = 0
        if urls:
            for url in urls:
                chart = self.loadChart(url)
                if chart:
                    atts.append(('chart%d.png' % count, chart))
                    count += 1
                else:
                    logging.error('unable to load chart: %s' % url)

        mail.send_mail(sender='bot@table2chart.appspotmail.com',
                       to=mail_message.sender,
                       subject='Re: ' + mail_message.subject,
                       body='see html ;-)',
                       html=content,
                       attachments=atts)


class MainHandler(webapp.RequestHandler):
    def get(self):
        self.response.out.write("""<!DOCTYPE html>
<head>
<title>table2chart</title>
<meta charset="utf-8">
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
</head>
<body>
<h1>table2chart - test form</h1>
<div>
<form method="POST">
<textarea name="html" cols="120" rows="20">
</textarea><br />
<input type=submit />
</form>
</div>
<div><a href="http://github.com/flow3r/table2chart"><img style="position: absolute; top: 0; right: 0; border: 0;" src="https://d3nwyuy0nl342s.cloudfront.net/img/e6bef7a091f5f3138b8cd40bc3e114258dd68ddf/687474703a2f2f73332e616d617a6f6e6177732e636f6d2f6769746875622f726962626f6e732f666f726b6d655f72696768745f7265645f6161303030302e706e67" alt="Fork me on GitHub"></a>
</div>
</body>
</html>
""")

    def post(self):
        html = self.request.get('html')
        #self.response.out.write(len(html))

        content = 'InputError: no table data found.'

        html = html and html.strip()
        if html:
            soup = BeautifulSoup(html)
            urls = get_graph_urls(soup)

            if urls:
                beg = '<img src="'
                end = '" /><br />'

                content = beg + (end+beg).join(urls) + end

        self.response.out.write(content)


def main():
    application = webapp.WSGIApplication([Table2ChartHandler.mapping(),
                                          ('/', MainHandler)],
                                         debug=True)
    run_wsgi_app(application)



if __name__ == '__main__':
    main()
