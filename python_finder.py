import os
import re
import sys
import threading
import sublime
import sublime_plugin


DEF_NOT_FOUND = 'Not Found'


class PythonFinderCommand(sublime_plugin.TextCommand):
    """
    A Sublime Plugin that allows you to search your Python classes and
    functions definition.
    """
    result_list = []

    def run(self, edit):
        """
        Run this command to find out where your Python classes and
        functions defined.
        """
        keywords = []
        imported_sources = []

        sels = self.view.sel()
        for s in sels:
            # Check if defined in current file.
            k = self.view.substr(s)
            r = self.view.find_all(r'def\s+{0}\s*\('.format(k))
            if not r:
                r = self.view.find_all(r'class\s+{0}\s*\('.format(k))
            if r:
                for item in r:
                    row, col = self.view.rowcol(item.begin())
                    result = '{0};{1};{2}'.format(
                        self.view.file_name(), row + 1, self.view.substr(item))
                    self.result_list.append(result)
                self.show_result()
                return

            # If not in current file, search in opened folders and system path
            test_import = sublime.Region(s.a - 1, s.b)
            sentinel = self.view.substr(test_import.begin())
            while re.match('[\w.]', sentinel):
                test_import = sublime.Region(test_import.a - 1, test_import.b)
                sentinel = self.view.substr(test_import.begin())
            keywords.append(self.view.substr(test_import)[1:])

        for key in keywords:
            imported = key.split('.')[0]
            result = self.view.find_all(
                r'\bfrom\s+(\S+\s)import.+{0}'.format(imported)
            )
            if not result:
                result = self.view.find_all(
                    r'\bimport.+({0})'.format(imported)
                )
                for r in result:
                    s = self.view.substr(r)
                    r = s.replace('import', '').strip().replace('.', '/')
                    imported_sources.append(r)
            else:
                for r in result:
                    s = self.view.substr(r)
                    r = s.replace('import', '').replace('from', '').strip()
                    source_path = r.split(' ')[0].strip().replace('.', '/')
                    imported_sources.append(source_path)
        imported_sources = list(set(imported_sources))

        # Get search path, starts from system path then user path.
        system_path = [p for p in sys.path
                       if os.path.isdir(p) and
                       p[-4:] != '.egg' and p[-9:] != '.egg-info']
        try:
            opened_folder = self.view.window().folders()[0] + '/'
        except IndexError:
            opened_folder = '.'
        search_path = system_path + [opened_folder]

        # Start a thread to do the search, avoid affecting normal use.
        threads = []
        thread = KeywordSearch(keywords, imported_sources, search_path)
        threads.append(thread)
        thread.start()

        self.handle_threads(threads)

    def handle_threads(self, threads):
        """
        Threads state handler.
        """
        next_threads = []
        for thread in threads:
            if thread.is_alive():
                next_threads.append(thread)
                continue
            if len(thread.result_list):
                # Latter search will overwrite previous result.
                self.result_list = thread.result_list

        threads = next_threads

        if len(threads):
            sublime.set_timeout(
                lambda: self.handle_threads(threads),
                100)
            return
        self.show_result()

    def show_result(self):
        self.view.sel().clear()
        current_window = self.view.window()
        self.result_list = self.result_list or [DEF_NOT_FOUND]
        current_window.show_quick_panel(self.result_list, self.open_selected)

    def open_selected(self, index):
        """
        Handles the popup window that contains the search result.
        """
        if index == -1 or self.result_list[index] == DEF_NOT_FOUND:
            self.result_list[:] = []
            return
        header_info = self.result_list[index].split(';')
        header_file = '{0}:{1}'.format(header_info[0], header_info[1])
        self.view.window().open_file(header_file, sublime.ENCODED_POSITION)
        self.result_list[:] = []


class KeywordSearch(threading.Thread):
    def __init__(self, keywords, imports, search_path):
        self.keywords = keywords
        self.imports = imports
        self.search_path = search_path
        self.result_list = []
        self.searched_import_list = []

        threading.Thread.__init__(self)

    def run(self):
        for keyword in self.keywords:
            if not keyword:
                continue
            self.search(self.imports, keyword)

    def get_func_pattern(self, keyword):
        return re.compile(r'def\s+{0}\s*\(.*\)\s*\:'.format(keyword))

    def get_class_pattern(self, keyword):
        return re.compile(r'class\s+{0}\s*\(.*\)\s*\:'.format(keyword))

    def search(self, imports, keyword):
        for source in imports:
            for path in self.search_path:
                file_name = os.path.join(path, source)
                if os.path.isdir(file_name):
                    file_name += '/__init__.py'
                    from_import_pattern = re.compile(
                        r'\bfrom\s+(\S+\s)import\s+{0}'.format(keyword),
                        flags=re.IGNORECASE)
                    import_all_pattern = re.compile(
                        r'\bfrom\s+(\S+{0}\s)import\s+\*'.format(keyword),
                        flags=re.IGNORECASE)
                    imported_sources = []
                    try:
                        with open(file_name, 'rb') as f:
                            for i, l in enumerate(f):
                                result = from_import_pattern.findall(l)
                                for r in result:
                                    imported_sources.append(
                                        r.strip().replace('.', '/'))
                                result = import_all_pattern.findall(l)
                                for r in result:
                                    imported_sources.append(
                                        r.strip().replace('.', '/'))
                    except IOError:
                        continue
                    if imported_sources:
                        self.search(imported_sources, keyword)
                else:
                    file_name += '.py'
                try:
                    with open(file_name, 'rb') as f:
                        key = keyword.split('.')[-1]
                        func_pattern = self.get_func_pattern(key)
                        class_pattern = self.get_class_pattern(key)
                        pattern = re.compile(r'\b{0}\b'.format(key))

                        for i, l in enumerate(f):
                            result = pattern.findall(l)
                            if result:
                                if not re.findall(func_pattern, l):
                                    if not re.findall(class_pattern, l):
                                        continue
                                result = '{0};{1};{2}'.format(file_name,
                                                              i + 1,
                                                              l)
                                self.result_list.append(result)
                except IOError:
                    continue
