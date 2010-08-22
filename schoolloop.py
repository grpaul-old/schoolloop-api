#!/usr/bin/python

import re, urllib, urllib2, time, sys, os
from BeautifulSoup import BeautifulSoup
from datetime import datetime

PAGE_TABLE = {
	'main' : '/portal/student_home',
	'dropbox' : '/student/drop_box',
	'calendar' : '/calendar/month'
}

class SchoolLoop(object):
	def __init__ (self, subdomain, https=True):
		"""
		Initializes the SchoolLoop object.
		
		- subdomain: subdomain on Schoolloop website (https://<subdomain>.schoolloop.com/)
		- https: set to False to disable https, enables debugging via Wireshark, etc.
		"""
	
		# schoolloop is so slow we can't waste time on unnecessary redirects
		class LoginRedirectHandler (urllib2.HTTPRedirectHandler, object):
			def __init__ (self):
				super(LoginRedirectHandler, self).__init__()
				self.enabled = False
				self.mode = 0 # 0 = disabled, 1 = login, 2 = stop redirect
			def redirect_request (self, *args):
				if self.mode == 1:
					if '/portal/login' in args[5]:
						return urllib2.Request('lr:///fail')
					else:
						return urllib2.Request('lr:///success')
				elif self.mode == 2:
					return urllib2.Request('lr:///%s' % urllib.quote (args[5]))
				else:
					return super(LoginRedirectHandler, self).redirect_request(*args)
			def lr_open (self, req):
				return req.get_selector()[1:]
		
		self.https = https
		self.subdomain = subdomain
		self.cache = {}
		self.lrHandler = LoginRedirectHandler()
		self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(), self.lrHandler)
		self.pages = {}
			
	def get_url (self, path):
		"""
		Converts an absolute path into a URL.
		
		- path: path to be converted to a URL
		"""
		return '%s://%s.schoolloop.com%s' % ('https' if self.https else 'http', self.subdomain, path)
		
	def login (self, user, pswd):
		"""
		Logs in to Schoolloop and establishes a session.
		
		- user: username
		- pswd: password
		"""
		self.lrHandler.mode = 1
		loginTry = self.opener.open(self.get_url('/portal/login?etarget=login_form'),
			urllib.urlencode([('login_name', user), ('password', pswd),
			('event.login.x', '0'), ('event.login.y', '0')]))
		self.lrHandler.mode = 0
		
		return loginTry == "success"
		
	def page(self, page, params=None):
		"""
		Fetches a page from Schoolloop, caches it, and returns a SchoolLoopPage object.
		
		- page: page keyword (see PAGE_TABLE)
		- params: GET params
		"""
		key = (page, params)
		if key in self.pages: return self.pages[key]
		self.pages[key] = SchoolLoopPage(self, PAGE_TABLE[page], params)
		self.pages[key].load()
		return self.pages[key]
		
	def class_list(self):
		"""
		Returns the list of classes as a list of tuples in the format
		of (course_group_id, course_name).
		"""
		classes = []
		table = self.page('main').soup.find('tbody', { 'class' : 'hub_general_body' })
		for row in table.findAll('tr'):
			anchor = row.find('td', {'class': 'left'}).a
			if anchor:
				course_group_id = re.search(r'group_id=(\d+)', anchor['href']).group (1)
				course_name = anchor.string
				if course_group_id and course_name:
					classes.append ((course_group_id, course_name))
		return classes
	
	def dropbox_files(self):
		"""
		Returns the list of files in the dropbox as a list of tuples in the
		format of (date, class, assignment_url, file_url).
		"""
		files = []
		table = self.page('dropbox').soup.find('div', { 'id' : 'container_content' }).findAll('table')[1]
		for el in table.findAll('tr')[1:]:
			cells = el.findAll('td')
			
			date = cells[0].string
			cls = cells[1].string
			assignment = (cells[2].a['href'], cells[2].a.string)
			file = (cells[3].a['href'], cells[3].a.string)
			
			files.append((date, cls, assignment, file))
		return files
		
	def assignment_list(self, class_filter=None):
		"""
		Returns a list of assignments, in the format: (state, title, class, due)
		
		- class_filter: a class tuple (id, name) to filter the assignments by.
		"""
		assignments = []
		table = self.page('main').soup.find(lambda tag: tag.string and tag.string.find('Current Assignments') != -1,
		 									{ 'class' : 'title' }).nextSibling.tbody
		assert table != None
		for row in table.findAll('tr'):
			cells = row.findAll('td')
			cells.pop(2); cells.pop(4)
			
			status = ('' if not cells[0].img else
			         'new' if cells[0].img['src'] == "https://cdn.schoolloop.com/1008131238/img/new.gif" 
			    else 'due' if cells[0].img['src'] == "https://cdn.schoolloop.com/1008131238/img/due.gif"
			    else '')
			title = (cells[1].div.a['href'], cells[1].div.a.string)
			cls = cells[2].div.string; cls = cls[:cls.rfind("Period") - 1]
			date = datetime.strptime(cells[3].div.string, '%m/%d/%y')
			
			assignments.append((status, title, cls, date))
		return assignments
			
	def calendar(self, year, month):
		"""
		Returns a list of events in the monthly calendar.
		
		- month: i don't even know what this does.
		"""
		events = []
		
		# show all events
		if 'calendar' not in self.pages:
			self.lrHandler.mode = 2
			self.opener.open(self.get_url('/calendar/setCalendarSettings'),
				'assigned=true&due=true&public=true&ugroups=true&uevents=true&x=0&y=0')
			self.lrHandler.mode = 0
		
		# stupid time zones
		if not self.timezone:
			soup = self.page('calendar').soup
			
			nowDate = int(soup.find('span', {'style': 'color : #AA0000;'}).string)
			
			nowTime = (lambda x: sum(x) / len(x))([int(re.search('month_id=(\d+)', y['href']).group(1))
				for y in soup.findAll(lambda x: x.name == "a" and
				x.has_key('href') and re.search('month_id=[^0]', x['href']))]) / 1000
			
			dt = datetime.utcfromtimestamp(nowTime)
			
			dst = False
			if dt.month == 3:
				# find the second sunday
				sunday = datetime.datetime(dt.year, 3, 8)
				while sunday.weekday () != 6:
					sunday = sunday.replace (day = sunday.day + 1)
				if dt.day > sunday.day:
					dst = True
			elif dt.month == 11:
				# find the first sunday
				sunday = datetime.datetime(dt.year, 11, 1)
				while sunday.weekday () != 6:
					sunday = sunday.replace (day = sunday.day + 1)
				if dt.day <= sunday.day:
					dst = True
			elif month > 3 and month < 11:
				dst = True
		
		table = self.page('calendar').soup.find('table', {'class': 'cal_table'})
		for td in table.findAll('td', {'class': 'cal_td'}):
			dateSpan = td.find('span')
			if (not dateSpan) or ('#888888' in dateSpan['style']):
				continue
		
		return events
		
class SchoolLoopPage(object):
	def __init__(self, loop, url, params):
		self.loop = loop
		self.url = url
		self.soup = None
		if params:
			self.url += "?" + params
	def load(self):
		pageHandle = self.loop.opener.open(self.loop.get_url(self.url))
		pageData = pageHandle.read()
		pageHandle.close()
		del pageHandle
		
		self.soup = BeautifulSoup(pageData)

def main(args):
	from optparse import OptionParser
	from getpass import getpass
	
	parser = OptionParser(usage="usage: %prog [options]",
		version="%prog 0.1")
	parser.add_option("-u", "--username",
		action="store",
		dest="username",
		default=None,
		help="Username to login. If unspecified, prompt from the terminal.")
	parser.add_option("-p", "--password",
		action="store",
		dest="password",
		default=None,
		help="Password to login. If unspecified, prompt from the terminal.")
	parser.add_option("-c", "--classes",
		action="store_true",
		dest="classes",
		default=False,
		help="Print classes.")
	parser.add_option("-d", "--dropbox",
		action="store_true",
		dest="dropbox",
		default=False,
		help="Print list of files in the dropbox.")
	parser.add_option("-e", "--events",
		action="store",
		dest="calendar",
		default=False,
		help="Print calendar.")
	parser.add_option("-a", "--assignments",
		action="store_true",
		dest="assignments",
		default=False,
		help="Print list of assignments.")
	(options, args) = parser.parse_args(args)

	username, password = options.username, options.password
	if not username: username = raw_input("Username: ")
	if not password: password = getpass("Password: ")
	
	s = SchoolLoop('lhs-sfusd-ca')
	if not s.login(username, password):
		print "error: unable to login"
		sys.exit()
	
	if options.classes: print s.class_list()
	if options.dropbox: print s.dropbox_files()
	if options.calendar: print s.calendar(int(options.calendar))
	if options.assignments: print s.assignment_list()

if __name__ == "__main__":
	main(sys.argv[1:])
