#!/usr/bin/python

import re, cookielib, threading, calendar, urllib, urllib2, time, sys, os
from BeautifulSoup import BeautifulSoup
from datetime import datetime, date as datedate # date conflicts too easily

PAGE_TABLE = {
	'main' : '/portal/student_home',
	'dropbox' : '/student/drop_box',
	'calendar' : '/calendar/month'
}

class PickleJar(cookielib.CookieJar, object):
	def __getstate__(self):
		state = self.__dict__.copy()
		del state['_cookies_lock']
		return state
	def __setstate__(self, state):
		self.__dict__ = state
		self._cookies_lock = threading.RLock()

class SchoolLoop(object):
	def __init__ (self, subdomain, https=True, cookiejar=None):
		"""
		Initializes the SchoolLoop object.
		
		- subdomain: subdomain on Schoolloop website (https://<subdomain>.schoolloop.com/)
		- https: set to False to disable https, enables debugging via Wireshark, etc.
		- cookiejar: cookiejar from previous session to speed up login
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
				return urllib.unquote (req.get_selector()[1:])
		
		self.https = https
		self.subdomain = subdomain
		self.cache = {}
		self.pages = {}
		self.lrHandler = LoginRedirectHandler()
		
		self.cookiejar = cookiejar
		if self.cookiejar is None:
			self.cookiejar = PickleJar()
		self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(self.cookiejar), self.lrHandler)
		
		self.timezone = None
			
	def get_url (self, path):
		"""
		Converts an absolute path into a URL.
		
		- path: path to be converted to a URL
		"""
		return '%s://%s.schoolloop.com%s' % (self.https and 'https' or 'http', self.subdomain, path)
		
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
	
	def login_status (self):
		"""
		Check if logged in.
		"""
		return bool(self.page('main', cache=False).soup)
	
	def page(self, page, params=None, cache=True):
		"""
		Fetches a page from Schoolloop, caches it, and returns a SchoolLoopPage object.
		
		- page: page keyword (see PAGE_TABLE)
		- params: GET params
		"""
		key = (page, params)
		if cache and key in self.pages: return self.pages[key]
		self.pages[key] = SchoolLoopPage(self, PAGE_TABLE[page], params)
		self.pages[key].load()
		return self.pages[key]
		
	def class_list(self):
		"""
		Returns the list of classes as a list of tuples in the format
		of (course_group_id, course_name, grade).
		"""
		classes = []
		table = self.page('main').soup.find('tbody', { 'class' : 'hub_general_body' })
		for row in table.findAll('tr'):
			anchor = row.find('td', {'class': 'left'}).a
			gradecell = [x for x in row.contents if type(x).__name__ == "Tag"][1]
			if anchor and gradecell:
				course_group_id = re.search(r'group_id=(\d+)', anchor['href']).group (1)
				course_name = anchor.string
				grade = ''
				if gradecell['class'] == "list_text" and not gradecell.a:
					grade = gradecell.contents[1]
				if course_group_id and course_name:
					classes.append ((course_group_id, course_name, grade))
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

			status = ''
			if cells[0].img:
				src = cells[0].img['src']
				status = ('new.gif' in src and 'new') or ('due.gif' in src and 'due') or ''
			
			title = (cells[1].div.a['href'], cells[1].div.a.string)
			cls = cells[2].div.string; cls = cls[:cls.rfind("Period") - 1]
			date = datetime(*(time.strptime(cells[3].div.string, '%m/%d/%y')[0:6])).date()
			
			assignments.append((status, title, cls, date))
		return assignments
			
	def calendar(self, month=None, year=None):
		"""
		Returns a list of events in the monthly calendar.
		Format: (date, id, course, description)
		Note that course can be None.
		
		- month: Month of events
		- year: Year of events
		"""
		events = []
		
		# show all events
		if 'calendar' not in self.pages:
			self.lrHandler.mode = 2
			self.opener.open(self.get_url('/calendar/setCalendarSettings'),
				'assigned=true&due=true&public=true&ugroups=true&uevents=true&x=0&y=0')
			self.lrHandler.mode = 0
		
		# stupid time zones
		if self.timezone is None:
			dt = datetime.utcfromtimestamp((lambda x: sum(x) / len(x))(
				[int(re.search('month_id=(\d+)', y['href']).group(1))
				for y in self.page('calendar').soup.findAll(lambda x: x.name == "a" and
				x.has_key('href') and re.search('month_id=[^0]', x['href']))]) / 1000)
			
			dst = False
			if dt.month == 3:
				# find the second sunday
				sunday = datetime(dt.year, 3, 8)
				while sunday.weekday () != 6:
					sunday = sunday.replace (day = sunday.day + 1)
				if dt.day > sunday.day:
					dst = True
			elif dt.month == 11:
				# find the first sunday
				sunday = datetime(dt.year, 11, 1)
				while sunday.weekday () != 6:
					sunday = sunday.replace (day = sunday.day + 1)
				if dt.day <= sunday.day:
					dst = True
			elif dt.month > 3 and dt.month < 11:
				dst = True
			
			self.timezone = -dt.hour
			if dst: self.timezone -= 1
		
		month_id = None
		if year or month:
			hour = -self.timezone
			if month > 3 and month <= 11: # DST
				hour -= 1
			month_id = calendar.timegm(datetime(year, month, 1, hour, 0, 0).timetuple()) * 1000
		
		soup = self.page('calendar', month_id and ('month_id=%d' % month_id) or None).soup
		table = soup.find('table', {'class': 'cal_table'})
		
		day_id = int(re.search(r'day_id=(\d+)', table.findAll('td', {'class': 'cal_td'})[15].a['href']).group(1)) / 1000
		dt = datetime.utcfromtimestamp(day_id)
		year = dt.year
		month = dt.month
		
		for td in table.findAll('td', {'class': 'cal_td'}):
			dateSpan = td.find('span')
			if (not dateSpan) or ('#888888' in dateSpan['style']):
				continue
			date = int(dateSpan.string)
			
			for div in td.findAll('div', style='font-size: 10px; font-weight: bold;'):
				a = div.a
				if not a: continue
				
				id = a['id']
				desc = a.string
			
				course = None
				if div.b:
					course = div.b.string
				
				events.append((datedate(year, month, date), id, course, desc))
		
		return events
		
class SchoolLoopPage(object):
	def __init__(self, loop, url, params):
		self.loop = loop
		self.url = url
		self.soup = None
		if params:
			self.url += "?" + params
	def load(self):
		self.loop.lrHandler.mode = 2
		pageHandle = self.loop.opener.open(self.loop.get_url(self.url))
		self.loop.lrHandler.mode = 0
		
		if isinstance (pageHandle, str):
			return
		
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
		action="store_true",
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
	if options.calendar: print s.calendar()
	if options.assignments: print s.assignment_list()

if __name__ == "__main__":
	main(sys.argv[1:])
