import sqlite3
import base64
from flask import Flask, request, send_from_directory
from flask_restful import Resource, Api
from flask_cors import CORS
import time
import math
import random
import string

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        if isinstance(row[idx], buffer):
            d[col[0]] = base64.b64encode(row[idx])
        else:
            d[col[0]] = row[idx]

    return d

conn = sqlite3.connect('demo.ncdb')
conn.row_factory = dict_factory

app = Flask(__name__)

CORS(app)

@app.route('/frontend/<path:path>')
def send_js(path):
    return send_from_directory('frontend', path)

api = Api(app)

def insert(tablename, rec):
    keys = ','.join(rec.keys())
    question_marks = ','.join(list('?'*len(rec)))
    values = tuple(rec.values())
    cursor = execute('INSERT INTO '+tablename+' ('+keys+') VALUES ('+question_marks+')', values)
    return cursor.lastrowid

def delete(tablename, note_id):
    execute("DELETE FROM " + tablename + " WHERE note_id = ?", [note_id])

def execute(sql, params=[]):
    cursor = conn.cursor()
    cursor.execute(sql, params)
    return cursor

def getResults(sql, params=[]):
    cursor = conn.cursor()
    query = cursor.execute(sql, params)
    return query.fetchall()

def getSingleResult(sql, params=()):
    cursor = conn.cursor()
    query = cursor.execute(sql, params)
    return query.fetchone()

class Query(Resource):
    def get(self):
        sql = request.args.get('sql')

        return getResults(sql)

api.add_resource(Query, '/query')

class Notes(Resource):
    def get(self, note_id):
        return {
            'detail': getSingleResult("select * from notes where note_id = ?", [note_id]),
            'formatting': getResults("select * from formatting where note_id = ? order by note_offset", [note_id]),
            'links': getResults("select * from links where note_id = ? order by note_offset", [note_id]),
            'images': getResults("select * from images where note_id = ? order by note_offset", [note_id])
        }

    def put(self, note_id):
        note = request.get_json(force=True)

        now = math.floor(time.time())

        execute("update notes set note_text = ?, note_title = ?, date_modified = ? where note_id = ?", [note['detail']['note_text'], note['detail']['note_title'], now, note_id])

        delete("formatting", note_id)

        for fmt in note['formatting']:
            insert("formatting", fmt)

        delete("images", note_id)

        for img in note['images']:
            img['image_data'] = buffer(base64.b64decode(img['image_data']))

            insert("images", img)

        delete("links", note_id)

        for link in note['links']:
            insert("links", link)

        conn.commit()

        return {}

    def delete(self, note_id):
        children = getResults("select note_id from notes_tree where note_pid = ?", [note_id])

        for child in children:
            self.delete(child['note_id'])

        delete("notes_tree", note_id)
        delete("notes", note_id)

        conn.commit()

api.add_resource(Notes, '/notes/<string:note_id>')

class NotesChildren(Resource):
    def post(self, parent_note_id):
        note = request.get_json(force=True)

        noteId = ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(22))

        if parent_note_id == "root":
            parent_note_id = ""

        new_note_pos = 0

        if note['target'] == 'into':
            res = getSingleResult('select max(note_pos) as max_note_pos from notes_tree where note_pid = ?', [parent_note_id])
            max_note_pos = res['max_note_pos']

            if max_note_pos is None: # no children yet
                new_note_pos = 0
            else:
                new_note_pos = max_note_pos + 1
        elif note['target'] == 'after':
            after_note = getSingleResult('select note_pos from notes_tree where note_id = ?', [note['target_note_id']])

            new_note_pos = after_note['note_pos'] + 1

            execute('update notes_tree set note_pos = note_pos + 1 where note_pid = ? and note_pos > ?', [parent_note_id, after_note['note_pos']])
        else:
            raise Exception('Unknown target: ' + note['target'])

        now = math.floor(time.time())

        insert("notes", {
            'note_id': noteId,
            'note_title': note['note_title'],
            'note_text': '',
            'note_clone_id': '',
            'date_created': now,
            'date_modified': now,
            'icon_info': 'pencil',
            'is_finished': 0
        })

        insert("notes_tree", {
            'note_id': noteId,
            'note_pid': parent_note_id,
            'note_pos': new_note_pos,
            'is_expanded': 0
        })

        conn.commit()

        return {
            'note_id': noteId
        }

api.add_resource(NotesChildren, '/notes/<string:parent_note_id>/children')

class MoveAfterNote(Resource):
    def put(self, note_id, after_note_id):
        after_note = getSingleResult("select * from notes_tree where note_id = ?", [after_note_id])

        if after_note <> None:
            execute("update notes_tree set note_pos = note_pos + 1 where note_pid = ? and note_pos > ?", [after_note['note_pid'], after_note['note_pos']])

            execute("update notes_tree set note_pid = ?, note_pos = ? where note_id = ?", [after_note['note_pid'], after_note['note_pos'] + 1, note_id])

            conn.commit()

api.add_resource(MoveAfterNote, '/notes/<string:note_id>/moveAfter/<string:after_note_id>')

class MoveBeforeNote(Resource):
    def put(self, note_id, before_note_id):
        before_note = getSingleResult("select * from notes_tree where note_id = ?", [before_note_id])

        if before_note <> None:
            execute("update notes_tree set note_pos = note_pos + 1 where note_id = ?", [before_note_id])

            execute("update notes_tree set note_pid = ?, note_pos = ? where note_id = ?", [before_note['note_pid'], before_note['note_pos'], note_id])

            conn.commit()

api.add_resource(MoveBeforeNote, '/notes/<string:note_id>/moveBefore/<string:before_note_id>')

class MoveToNote(Resource):
    def put(self, note_id, parent_id):
        res = getSingleResult('select max(note_pos) as max_note_pos from notes_tree where note_pid = ?', [parent_id])
        max_note_pos = res['max_note_pos']
        new_note_pos = 0

        if max_note_pos is None: # no children yet
            new_note_pos = 0
        else:
            new_note_pos = max_note_pos + 1

        execute("update notes_tree set note_pid = ?, note_pos = ? where note_id = ?", [parent_id, new_note_pos, note_id])

        conn.commit()

api.add_resource(MoveToNote, '/notes/<string:note_id>/moveTo/<string:parent_id>')

class ExpandedNote(Resource):
    def put(self, note_id, expanded):
        execute("update notes_tree set is_expanded = ? where note_id = ?", [expanded, note_id])

        conn.commit()

api.add_resource(ExpandedNote, '/notes/<string:note_id>/expanded/<int:expanded>')

class Tree(Resource):
    def get(self):
        notes = getResults("select notes_tree.*, notes.note_title from notes_tree join notes on notes.note_id = notes_tree.note_id order by note_pid, note_pos")

        rootNotes = []
        notesMap = {}

        for note in notes:
            note['children'] = []

            if not note['note_pid']:
                rootNotes.append(note)

            notesMap[note['note_id']] = note

        for note in notes:
            if note['note_pid'] != "":
                parent = notesMap[note['note_pid']]

                parent['children'].append(note)
                parent['folder'] = True

        return rootNotes

api.add_resource(Tree, '/tree')

if __name__ == '__main__':
    app.run(host='0.0.0.0')