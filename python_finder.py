import os
import re
import threading
import sublime
import sublime_plugin


DEF_NOT_FOUND = 'Not Found'


def get_imported_source(file_name):
    source_name = {}
    file_content = ''
    source = ''
    word = ''
    from_tag = False
    import_tag = False
    import_brackets_tag = False
    import_comma_tag = False
    next_line_tag = False

    try:
        with open(file_name, 'rb') as f:
            for line in f:
                file_content += line
    except IOError:
        return source_name

    for w in file_content:
        if not w:
            continue
        if w == '\n':
            next_line_tag = False
            import_comma_tag = False
        elif w != ' ' and w != '\t':
            word += w
            continue

        if not word:
            continue
        elif word == 'from':
            from_tag = True
            import_brackets_tag = False
            import_comma_tag = False
            word = ''
        elif word == 'import':
            import_tag = True
            import_brackets_tag = False
            import_comma_tag = False
            word = ''
        else:
            if from_tag:
                upper_dir = 0
                while upper_dir < len(word) - 1 and word[upper_dir] == '.':
                    upper_dir += 1
                word = word[upper_dir:]
                if upper_dir != 0:
                    folder = '/'.join(file_name.split('/')[:-upper_dir])
                    word = folder + '/' + word
                source = word
                if source not in source_name:
                    source_name[source] = []
                from_tag = False
            elif import_tag:
                replace_str = []
                if '(' in word:
                    replace_str.append('(')
                    import_brackets_tag = True
                if ')' in word:
                    replace_str.append(')')
                    import_brackets_tag = False
                if ',' in word:
                    replace_str.append(',')
                    import_comma_tag = True
                if '\\' in word:
                    replace_str.append('\\')
                    next_line_tag = True
                for s in replace_str:
                    word = word.replace(s, '')

                if word:
                    try:
                        source_name[source].append(word)
                    except KeyError:
                        source_name[word] = [word]

                if not (import_brackets_tag or
                        import_comma_tag or next_line_tag):
                    import_tag = False
            word = ''
    return source_name


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
            source_name = get_imported_source(self.view.file_name())
            for k in source_name:
                if imported in source_name[k]:
                    imported_sources.append(k.replace('.', '/'))

        # Get search path
        try:
            opened_folder = self.view.window().folders()[0] + '/'
        except IndexError:
            opened_folder = '.'
        search_path = [opened_folder]

        # Trim the imported sources, mainly for relative import
        trimmed_sources = []
        for s in imported_sources:
            trimmed_sources.append(s.replace(opened_folder, ''))

        # Start a thread to do the search, avoid affecting normal use.
        threads = []
        thread = KeywordSearch(keywords, trimmed_sources, search_path)
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
        """
        Display the search result in a popup panel.
        """
        self.view.sel().clear()
        current_window = self.view.window()
        self.result_list = list(set(self.result_list))
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
        return re.compile(r'def\s+{0}\s*\(.*'.format(keyword))

    def get_class_pattern(self, keyword):
        return re.compile(r'class\s+{0}\s*\(.*\)\s*\:'.format(keyword))

    def detect_keyword_file(self, file_name):
        try:
            with open(file_name, 'rb'):
                result = '{0};{1};'.format(file_name, 1)
                self.result_list.append(result)
                return True
        except IOError:
            return False

    def search(self, imports, keyword):
        for source in imports:
            for path in self.search_path:
                file_name = os.path.join(path, source)

                if os.path.isdir(file_name):
                    init_file_name = file_name + '/__init__.py'
                    imported_sources = []
                    source_name = get_imported_source(init_file_name)
                    for k in source_name:
                        if keyword in source_name[k]:
                            imported_sources.append(k.replace('.', '/'))
                    if not imported_sources:
                        imported_sources.append('__init__')
                    self.search_path.append(file_name)
                    self.search(imported_sources, keyword)

                    keyword_file_name = file_name + '/' + keyword + '.py'
                    if self.detect_keyword_file(keyword_file_name):
                        continue
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
