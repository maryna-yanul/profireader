import os
import re
from flask import render_template, g, make_response
from profapp.models.files import File, YoutubeApi
from .blueprints_declaration import filemanager_bp
from .request_wrapers import ok, tos_required
from functools import wraps
from flask import jsonify, json
import json as jsonmodule
from flask.ext.login import login_required
from flask import session, redirect, request, url_for
from ..models.google import GoogleAuthorize, GoogleToken
from utils.db_utils import db
from ..models.company import Company, UserCompany
import urllib.parse



def parent_folder(func):
    @wraps(func)
    def function_parent_folder(json, *args, **kwargs):
        ret = func(json, *args, **kwargs)
        return ret

    return function_parent_folder


# TODO: VK by OZ: what is that (root)?
root = os.getcwd() + '/profapp/static/filemanager/tmp'
json_result = {"result": {"success": True, "error": None}}


@filemanager_bp.route('/')
@login_required
@tos_required
def filemanager():
    last_visit_root_name = ''
    if 'last_root' in request.cookies:
        last_root_id = request.cookies['last_root']
    else:
        last_root_id = ''

    library = []
    members, main_companies = Company.get_members_for_company()
    uniq = set()
    for n, user_company in enumerate(g.user.employer_assoc):
        if user_company.has_rights(UserCompany.RIGHT_AT_COMPANY.FILES_BROWSE):
            library.insert(n, File.folder_dict(user_company.employer,
                                               {'can_upload': File.if_action_allowed(File.ACTIONS['upload'], user_company.company_id)}))
            uniq.update({user_company.employer.name})
            if user_company.employer.journalist_folder_file_id == last_root_id:
                last_visit_root_name = user_company.employer.name + " files"
            if user_company.employer.name in members:
                for member in members[user_company.employer.name]:
                    if member.company.name not in uniq and member.company.name not in main_companies:
                        library.append(File.folder_dict(member.company,
                                                        {'can_upload': File.if_action_allowed(File.ACTIONS['upload'], member.company.id)}))
                        uniq.update({member.company.name})
                        if member.company.journalist_folder_file_id == last_root_id:
                            last_visit_root_name = member.company.name + " files"
    # library.sort(key=lambda k: k['name'])
    file_manager_called_for = request.args[
        'file_manager_called_for'] if 'file_manager_called_for' in request.args else ''
    file_manager_on_action = jsonmodule.loads(
        request.args['file_manager_on_action']) if 'file_manager_on_action' in request.args else {}
    file_manager_default_action = request.args[
        'file_manager_default_action'] if 'file_manager_default_action' in request.args else 'download'
    get_root = request.args[
        'get_root'] if 'get_root' in request.args else None
    if get_root:
        root = Company.get(get_root)
        last_visit_root_name = (root.name + " files") if root else ''
        last_root_id = root.journalist_folder_file_id if root else ''
    err = True if len(library) == 0 else False
    return render_template('filemanager.html', library=json.dumps(library), err=err, last_visit_root=last_visit_root_name.replace(
        '"', '_').replace('*', '_').replace('/', '_').replace('\\', '_').replace('\'', '_'),
                           last_root_id=last_root_id,
                           file_manager_called_for=file_manager_called_for,
                           file_manager_on_action=file_manager_on_action,
                           file_manager_default_action=file_manager_default_action)


@filemanager_bp.route('/list/', methods=['POST'])
@ok
def list(json):
    ancestors = File.ancestors(json['params']['folder_id'])
    company = db(Company, journalist_folder_file_id=ancestors[0]).first()
    if len(json['params'].get('search_text'))>0:
        list = File.list(json['params']['folder_id'], json['params']['file_manager_called_for'],
                         json['params']['search_text'], company_id=company.id)
    else:
        list = File.list(json['params']['folder_id'], json['params']['file_manager_called_for'],company_id=company.id)
    return {'list': list, 'ancestors': ancestors}

@filemanager_bp.route('/createdir/', methods=['POST'])
@ok
def createdir(json):
    if not File.if_action_allowed('upload', get_company_from_folder(json['params']['root_id']).id):
        return False
    return File.createdir(name=json['params']['name'],
                          root_folder_id=json['params']['root_id'],
                          parent_id=json['params']['folder_id'])


@filemanager_bp.route('/properties/', methods=['POST'])
@ok
def set_properties(json):
    file = File.get(json['params']['id'])
    if not file or not File.if_action_allowed('upload', get_company_from_folder(json['params']['id']).id):
        return False
    return File.set_properties(file, json['params']['add_all'], name=json['params']['name'],
                               copyright_author_name=json['params']['author_name'],
                               description=json['params']['description'])


@filemanager_bp.route('/copy/', methods=['POST'])
@ok
def copy(json):
    file = File.get(json['params']['id'])
    if not file or not File.if_action_allowed('upload', get_company_from_folder(json['params']['id']).id):
        return False
    return file.copy_file(json['params']['folder_id']).id


@filemanager_bp.route('/cut/', methods=['POST'])
@ok
def cut(json):
    file = File.get(json['params']['id'])
    if not file or not File.if_action_allowed('upload', get_company_from_folder(json['params']['id']).id):
        return False
    return file.move_to(json['params']['folder_id'])


@filemanager_bp.route('/auto_remove/', methods=['POST'])
@ok
def auto_remove(json):
    return File.auto_remove(json.get('list'))

def get_company_from_folder(file_id):
    ancestors = File.ancestors(file_id)
    return db(Company, journalist_folder_file_id=ancestors[0]).first()

@filemanager_bp.route('/remove/<string:file_id>', methods=['POST'])
@ok
def remove(json, file_id):
    file = File.get(file_id)
    if not file:
        return False
    ancestors = File.ancestors(file.parent_id)
    return file.remove(db(Company, journalist_folder_file_id=ancestors[0]).first().id)


@filemanager_bp.route('/uploader/', methods=['GET', 'POST'])
@filemanager_bp.route('/uploader/<string:company_id>', methods=['GET', 'POST'])
def uploader(company_id=None):
    token_db_class = GoogleToken()
    credentials_exist = token_db_class.check_credentials_exist()
    google = GoogleAuthorize()
    if not credentials_exist and google.check_admins():
        if 'code' in request.args:
            session['auth_code'] = request.args['code']
            token_db_class.save_credentials()
        return redirect(url_for('company.companies')) if 'code' in request.args \
            else redirect(google.get_auth_code())
    return render_template('file_uploader.html', company_id=company_id)


@filemanager_bp.route('/send/<string:parent_id>/', methods=['POST'])
def send(parent_id):
    parent = File.get(parent_id)
    root = parent.root_folder_id
    if parent.mime == 'root':
        root = parent.id
    company = db(Company, journalist_folder_file_id=root).one()
    if File.if_action_allowed('upload', company.id) == False:
        return jsonify({'error': True })
    data = request.form
    uploaded_file = request.files['file']
    name = File.get_unique_name(urllib.parse.unquote(uploaded_file.filename).replace(
        '"', '_').replace('*', '_').replace('/', '_').replace('\\', '_'), data.get('ftype'), parent.id)
    data.get('ftype')
    if re.match('^video/.*', data.get('ftype')):
        body = {'title': uploaded_file.filename,
                'description': '',
                'status': 'public'}
        youtube = YoutubeApi(body_dict=body,
                             video_file=uploaded_file.stream.read(-1),
                             chunk_info=dict(chunk_size=int(data.get('chunkSize')),
                                             chunk_number=int(data.get('chunkNumber')),
                                             total_size=int(data.get('totalSize'))),
                             company_id=company.id,
                             root_folder_id=company.journalist_folder_file_id,
                             parent_folder_id=parent_id)
        file = youtube.upload()
    else:
        file = File.upload(name, data, parent.id, root, company, content=uploaded_file.stream.read(-1))
    return jsonify({'result': {'size': 0}, 'error': True if file=='error' else False, 'file_id':file})


@filemanager_bp.route('/resumeupload/', methods=['GET'])
def resumeupload():
    return jsonify({'size': 0})
