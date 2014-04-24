import sublime, sublime_plugin
from simplenote import Simplenote

from os import path, makedirs, remove, listdir
from datetime import datetime

from operations import NoteCreator, NoteDownloader, MultipleNoteDownloader, NoteDeleter, NoteUpdater

def cmp_to_key(mycmp):
    'Convert a cmp= function into a key= function'
    class K(object):
        def __init__(self, obj, *args):
            self.obj = obj
        def __lt__(self, other):
            return mycmp(self.obj, other.obj) < 0
        def __gt__(self, other):
            return mycmp(self.obj, other.obj) > 0
        def __eq__(self, other):
            return mycmp(self.obj, other.obj) == 0
        def __le__(self, other):
            return mycmp(self.obj, other.obj) <= 0
        def __ge__(self, other):
            return mycmp(self.obj, other.obj) >= 0
        def __ne__(self, other):
            return mycmp(self.obj, other.obj) != 0
    return K

def sort_notes(a_note, b_note):
	if 'pinned' in a_note['systemtags']:
		return 1
	elif 'pinned' in b_note['systemtags']:
		return -1
	else:
		date_a = datetime.fromtimestamp(float(a_note['modifydate']))
		date_b = datetime.fromtimestamp(float(b_note['modifydate']))
		return cmp(date_a, date_b)

def show_message(message):
	if not message:
		message = ''
	for window in sublime.windows():
			for currentView in window.views():
				currentView.set_status('QuickSimplenote', message)

def remove_status():
	show_message(None)

def open_note(note):
	filepath = get_path_for_note(note)
	if not path.exists(filepath):
		f = open(filepath, 'w')
		try:
			content = note['content']
			f.write(content)
		except KeyError:
			pass
		f.close()
	sublime.active_window().open_file(filepath)

def get_path_for_note(note):
	return path.join(temp_path, note['key'])

def get_note_from_path(view_filepath):
	note = None
	if path.dirname(view_filepath) == temp_path:
		note_key = path.split(view_filepath)[1]
		note = [note for note in notes if note['key'] == note_key][0]
	
	return note

def close_view(view):
	view.set_scratch(True)
	view.window().focus_view(view)
	view.window().run_command("close_file")

class OperationManager:
    _instance = None
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(OperationManager, *args, **kwargs)
        return cls._instance

    def __init__(self):
        self.operations = deque([])
        self.running = False
        self.current_operation = None

    def add_operation(self, operation):
        self.operations.append(operation)
        if (not self.running):
            self.run()

    def check_operations(self):

        if self.current_operation == None:
            return

        # If it's still running, update the status
        if self.current_operation.is_alive():
            text = self.current_operation.get_update_run_text()
        else:
            # If not running, show finished text
            # call callback with result and do the
            # next operation
            text = self.current_operation.get_run_finished_text()
            self.current_operation.join()
            if len( self.operations ) > 0:
                self.start_next_operation()
            else:
                self.running = False
                sublime.set_timeout(remove_status, 1000)

        show_message(text)
        if self.running:
            sublime.set_timeout(self.check_operations, 1000)

    def run(self):
        self.start_next_operation()
        sublime.set_timeout(self.check_operations, 1000)
        self.running = True

    def start_next_operation(self):
        self.current_operation = self.operations.popleft()
        self.current_operation.start()

class HandleNoteViewCommand(sublime_plugin.EventListener):

	def check_updater(self):
		global notes

		if self.progress >= 3:
			self.progress = 0
		self.progress += 1

		if self.updater.is_alive():
			show_message('QuickSimplenote: Uploading note%s' % ( '.' * self.progress) )
			sublime.set_timeout(self.check_updater, 1000)
		else:
			# We get all data back except the content of the note
			# we need to merge it ourselves
			modified_note_resume = self.updater.join()
			for index, note in enumerate(notes):
				if note['key'] == modified_note_resume['key']:
					modified_note_resume['content'] = note['content']
					notes[index] = modified_note_resume
					break
			notes.sort(key=cmp_to_key(sort_notes), reverse=True)

			show_message('QuickSimplenote: Done')
			sublime.set_timeout(remove_status, 2000)

	def on_post_save(self, view):
		self.progress = -1

		view_filepath = view.file_name()
		note = get_note_from_path(view_filepath)
		if note:
			note['content'] = view.substr(sublime.Region(0, view.size())).encode('utf-8')
			self.updater = NoteUpdater(note=note, simplenote_instance=simplenote_instance)
			self.updater.start()
			sublime.set_timeout(self.check_updater, 1000)

class ShowQuickSimplenoteNotesCommand(sublime_plugin.ApplicationCommand):

	def get_note_name(self, note):
		try:
			content = note['content']
		except Exception, e:
			return 'untitled'
		index = content.find('\n');
		if index > -1:
			title = content[:index]
		else:
			if content:
				title = content
			else:
				title = 'untitled'
		title = title.decode('utf-8')
		return title

	def handle_selected(self, selected_index):
		if not selected_index > -1:
			return

		selected_note = notes[selected_index]
		open_note(selected_note)

	def run(self):
		if not started:
			if not start():
				return

		i = 0
		keys = []
		for note in	notes:
			i += 1
			title = self.get_note_name(note)
			keys.append(title)
		sublime.active_window().show_quick_panel(keys, self.handle_selected)

class StartQuickSimplenoteCommand(sublime_plugin.ApplicationCommand):

	def set_result(self, new_notes):
		global notes
		notes = new_notes
		print(notes)

	def run(self):
		self.progress = -1

		show_message('QuickSimplenote: Setting up')
		if not path.exists(temp_path):
			makedirs(temp_path)
		for f in listdir(temp_path):
			remove(path.join(temp_path, f))

		show_message('QuickSimplenote: Downloading notes')
		download_op = MultipleNoteDownloader(simplenote_instance=simplenote_instance)
		download_op.set_callback(self.set_result)
		OperationManager().add_operation(download_op)

class CreateQuickSimplenoteNoteCommand(sublime_plugin.ApplicationCommand):

	def check_creation(self):
		if self.progress >= 3:
			self.progress = 0
		self.progress += 1
		if self.creation_thread.is_alive():
			show_message('QuickSimplenote: Creating note%s' % ( '.' * self.progress) )
			sublime.set_timeout(self.check_creation, 1000)
		else:
			global notes
			note = self.creation_thread.join()
			notes.append(note)
			notes.sort(key=cmp_to_key(sort_notes), reverse=True)
			show_message('QuickSimplenote: Done')
			sublime.set_timeout(remove_status, 2000)
			open_note(note)

	def run(self):
		self.progress = -1

		show_message('QuickSimplenote: Creating note')
		self.creation_thread = NoteCreator(simplenote_instance=simplenote_instance)
		self.creation_thread.start()
		self.check_creation()

class DeleteQuickSimplenoteNoteCommand(sublime_plugin.ApplicationCommand):

	def check_deletion(self):
		if self.progress >= 3:
			self.progress = 0
		self.progress += 1
		if self.deletion_thread.is_alive():
			show_message('QuickSimplenote: Deleting note%s' % ( '.' * self.progress) )
			sublime.set_timeout(self.check_deletion, 1000)
		else:
			global notes
			notes.remove(self.note)
			remove(get_path_for_note(self.note))
			close_view(self.note_view)
			show_message('QuickSimplenote: Done')
			sublime.set_timeout(remove_status, 2000)

	def run(self):
		self.progress = -1
		self.note_view = sublime.active_window().active_view()
		self.note = get_note_from_path(self.note_view.file_name())
		if self.note:
			show_message('QuickSimplenote: Deleting note')
			self.deletion_thread = NoteDeleter(note=self.note, simplenote_instance=simplenote_instance)
			self.deletion_thread.start()
			self.check_deletion()

def start():
	global started, simplenote_instance, settings

	username = settings.get('username')
	password = settings.get('password')

	if (username and password):
		simplenote_instance = Simplenote(username, password)
		sublime.run_command('start_quick_simplenote');
		started = True
	else:
		filepath = path.join(package_path, 'quick_simplenote.sublime-settings')
		sublime.active_window().open_file(filepath)
		show_message('QuickSimplenote: Please configure username/password')
		sublime.set_timeout(remove_status, 2000)
		started = False

	return started

simplenote_instance = None
started = False
notes = []
package_path = path.join(sublime.packages_path(), "QuickSimplenote")
temp_path = path.join(package_path, "temp")

settings = sublime.load_settings('quick_simplenote.sublime-settings')

if settings.get('autostart'):
	print('QuickSimplenote: Autostarting')
	sublime.set_timeout(start, 2000) # I know...
