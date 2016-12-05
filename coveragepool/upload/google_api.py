import gspread
from oauth2client.service_account import ServiceAccountCredentials

class GoogleSheetMGR(object):
    def __init__(self, key="1wGH-K5uLpLS889BD-_SYJX18fNaFoJSyl5iP06oWFlw", sheet=None, json_file=None):
        self.key = key
        self.sheet = sheet
        if json_file:
            self.json_file = json_file
        else:
            self.json_file = "/root/gspread2.json"

        self._authorize()

        self.keys = self.get_keys()

    def _authorize(self):
        """
        See: http://gspread.readthedocs.io/en/latest/oauth2.html
        """
        scope = ['https://spreadsheets.google.com/feeds']
        credentials = ServiceAccountCredentials.from_json_keyfile_name(self.json_file, scope)
        gc = gspread.authorize(credentials)
        self.Worksheet = gc.open_by_key(self.key)

        if self.sheet:
            self.ws_obj = self.Worksheet.get_worksheet(self.sheet)
        else:
            self.ws_obj = self.Worksheet.sheet1

    def get_all_values(self):
        return self._get_all_values()

    def _worksheet_action(self, action, *args):
        """
        Wrap gspread worksheet actions to make sure no authorization issue
        """
        retry = 0
        max_retry = 5
        while True:
            try:
                func = getattr(self.ws_obj, action)
                return func(*args)
            except gspread.exceptions.HTTPError as details:
                self._authorize()
                retry += 1
                if retry > max_retry:
                    raise details

    def _get_all_values(self):
        """
        Get all values from worksheet
        """
        return self._worksheet_action('get_all_values')

    def _update_cell(self, *args):
        """
        Update a cell in spreadsheet
        """
        return self._worksheet_action('update_cell', *args)

    def get_keys(self):
        """
        1st row is the key
        """
        return self._get_all_values()[0]

    def rework_sheet(self, data):
        old_data = self.get_all_values()

        for i_row, row_data in enumerate(old_data):
            for i_cell, cell_data in enumerate(row_data):
                new_val = data[i_row][i_cell]
                if new_val != cell_data:
                    self._update_cell(i_row, i_cell, new_val)

    def add_new_row(self, row_data, row=None):
        if row:
            new_row = row
        else:
            new_row = len(self._get_all_values()) + 1

        for index, cell_data in enumerate(row_data):
            self._update_cell(new_row, index + 1, cell_data)

    def add_new_row_by_dict(self, data_dict, row=None):
        if row:
            new_row = row
        else:
            new_row = len(self._get_all_values()) + 1

        for index, key in enumerate(self.keys):
            if key in data_dict.keys():
                self._update_cell(new_row, index + 1, data_dict[key])

    def search_update_by_dict(self, search_dict, data_dict):
        table = self._get_all_values()
        index_dict = {}
        index_dict2 = {}
        for index, key in enumerate(self.keys):
            if key in search_dict.keys():
                index_dict[index] = search_dict[key]
            if key in data_dict.keys():
                index_dict2[index] = data_dict[key]

        for row, i in enumerate(table):
            for index, val in index_dict.items():
                if i[index] != val:
                    found = False
                    break
                else:
                    found = True

            if not found:
                continue

            for key, val in index_dict2.items():
                self._update_cell(row + 1, key + 1, val)
