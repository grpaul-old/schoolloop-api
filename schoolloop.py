#!/usr/bin/python

import re, urllib, urllib2, sys, os
from BeautifulSoup import BeautifulSoup

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
		
	def page(self, page):
		"""
		Fetches a page from Schoolloop, caches it, and returns a SchoolLoopPage object.
		
		- page: page keyword (see PAGE_TABLE)
		"""
		if self.pages.has_key(page): return self.pages[page]
		self.pages[page] = SchoolLoopPage(self, PAGE_TABLE[page])
		self.pages[page].load()
		return self.pages[page]
		
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

	def calendar(self, month):
		"""
		Returns a list of events in the monthly calendar.
		
		- month: unix time that determines the month and year of the calendar
		"""
		events = []
		# TODO: implement this
		return events
		
class SchoolLoopPage(object):
	def __init__(self, loop, url):
		self.loop = loop
		self.url = url
		self.soup = None
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
	(options, args) = parser.parse_args(args)

	username, password = options.username, options.password
	if not username: username = raw_input("Username: ")
	if not password: password = getpass("Password: ")
	
	s = SchoolLoop('lhs-sfusd-ca')
	if not s.login(username, password):
		print "error: unable to login"
	
	if options.classes: print s.class_list()
	if options.dropbox: print s.dropbox_files()
	if options.calendar: print s.calendar(int(options.calendar))

if __name__ == "__main__":
	main(sys.argv[1:])
