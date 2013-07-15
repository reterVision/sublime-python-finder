import ast
import os
import re
import threading
import sublime
import sublime_plugin

DEF_NOT_FOUND = 'Not Found'


def get_ast(file_name):
    """
    Generate AST using Python library.
    """
    file_content = ''
    try:
        with open(file_name, 'rb') as f:
            for line in f:
                file_content += line
    except IOError:
        return None
    return ast.parse(file_content)


def get_imported_source(file_name):
    """
    Extract imported libraries using Python's AST.
    """
    source_name = {}
    expr_ast = get_ast(file_name)
    if expr_ast is None:
        return source_name
    return lookup_ast(expr_ast, source_name)


def lookup_ast(expr_ast, source_name):
    for node in expr_ast.body:
        if isinstance(node, ast.Import):
            for name in node.names:
                try:
                    source_name[name.name].append(name.name)
                except KeyError:
                    source_name[name.name] = [name.name]
        elif isinstance(node, ast.ImportFrom):
            for name in node.names:
                try:
                    source_name[node.module].append(name.name)
                except KeyError:
                    source_name[node.module] = [name.name]
        if getattr(node, 'body', False):
            lookup_ast(node, source_name)
    return source_name


def search_def(ast_body, file_name, keyword, result_list):
    """
    Search keyword definition in current file.
    """
    for node in ast_body:
        if isinstance(node, ast.FunctionDef):
            if node.name == keyword:
                result_list.append('{0};{1};'.format(file_name, node.lineno))
        if isinstance(node, ast.ClassDef):
            if node.name == keyword:
                result_list.append('{0};{1};'.format(file_name, node.lineno))
            search_def(node.body, file_name, keyword, result_list)


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
            current_file_name = self.view.file_name()
            expr_ast = get_ast(current_file_name)
            search_def(expr_ast.body, current_file_name, k, self.result_list)
            if self.result_list:
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
            sublime.set_timeout(lambda: self.handle_threads(threads), 100)
            return
        self.show_result()

    def show_result(self):
        """
        Display the search result in a popup panel.
        """
        self.view.sel().clear()
        current_window = self.view.window()
        self.result_list = list(set(self.result_list)) or [DEF_NOT_FOUND]
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

                expr_ast = get_ast(file_name)
                if expr_ast is None:
                    continue
                search_def(expr_ast.body, file_name, keyword, self.result_list)
