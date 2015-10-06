# from apiclient import discovery
from config import Config
import httplib2
from flask import session
from oauth2client import client
from oauth2client.client import Credentials
from urllib import request as req
from urllib import parse
from ..constants.TABLE_TYPES import TABLE_TYPES
from sqlalchemy import Column, ForeignKey
from .pr_base import Base, PRBase
from flask import g
from utils.db_utils import db
from urllib.error import HTTPError as response_code
import sys
import json
from ..controllers.errors import TooManyCredentialsInDb

class GoogleToken(Base, PRBase):
    __tablename__ = 'google_token'
    id = Column(TABLE_TYPES['id_profireader'], primary_key=True)
    credentials = Column(TABLE_TYPES['credentials'], nullable=False)
    kind = Column(TABLE_TYPES['string_30'])

    def __init__(self, credentials=None, kind=None):
        super(GoogleToken, self).__init__()
        self.credentials = credentials
        self.kind = kind

    @staticmethod
    def check_credentials_exist(kind=None):
        """ Method check rather credentials is exist in db. Can be only one credentials in db.
         kind should be update, playlist
         If None you should to redirect admin to google auth page.
         If >1 some think is wrong . Raise exception"""
        try:
            credentials = db(GoogleToken, kind=kind).count()
            if credentials < 2:
                return credentials
            else:
                raise TooManyCredentialsInDb({'message': 'credentials >1'})
        except TooManyCredentialsInDb as e:
            e = e.args[0]
            print(e['message'])

    def save_credentials(self, kind=None):
        """ This method save and return your credentials to/from db in json format.
         When you will need credentials you have to convert json to object(
         method: Credentials().new_from_json ) """
        google = GoogleAuthorize()
        flow = google.get_auth_code(ret_flow=True)
        credentials = flow.step2_exchange(session['auth_code'])
        self.credentials, self.kind = credentials.to_json(), kind
        self.save()
        return self.credentials

    @staticmethod
    def get_credentials_from_db():
        """ Static method. This method make query from db to get json-credentials, and
         then return object correct credentials which has been made from json.
          Set httplib2.debuglevel = 4 to debug http"""
        # httplib2.debuglevel = 4
        json = db(GoogleToken).first().credentials
        cred = Credentials()
        credentials = cred.new_from_json(json)
        http = httplib2.Http()
        http = credentials.authorize(http)
        credentials.refresh(http)
        session['access_token'] = credentials.access_token
        return credentials

    @staticmethod
    def get_authorize_http():
        """ Method which is helpful to get authorize http from your credentials.
         Can be used for make some service from google api"""
        json = db(GoogleToken).first().credentials
        cred = Credentials()
        credentials = cred.new_from_json(json)
        http = httplib2.Http()
        http = credentials.authorize(http)
        return http

class GoogleAuthorize(object):
    """ This class can apply api_service name and api_version to build service which you want.
     Default youtube upload service. Method authorize return service with necessary token
     server-server . If you need to get token, use flask.session['credentials'] """

    __project_secret = Config.GOOGLE_API_SECRET_JSON

    def __init__(self, google_service_name=Config.YOUTUBE_API_SERVICE_NAME,
                 google_service_version=Config.YOUTUBE_API_VERSION,
                 scope=Config.YOUTUBE_API['UPLOAD']['SCOPE'],
                 redirect_uri=Config.YOUTUBE_API['UPLOAD']['REDIRECT_URI']):
        self.google_service_name = google_service_name
        self.google_service_version = google_service_version
        self.scope = scope
        self.redirect_uri = redirect_uri

    def get_auth_code(self, ret_flow=False):

        """ This method return link for google auth service if ret_flow parameter is not produced,
        else - return flow object. Helpful when you need to have code to make credentials """
        flow = client.flow_from_clientsecrets(self.__project_secret, self.scope,
                                              redirect_uri=self.redirect_uri)
        flow.params['access_type'] = 'offline'
        flow.params['approval_prompt'] = 'force'
        auth_uri = flow.step1_get_authorize_url()
        request_for_token = req.urlopen(auth_uri)
        url = request_for_token.geturl()
        return url if not ret_flow else flow

    @staticmethod
    def check_admins():
        """ This method check if current user is profireader admin. Return True or False """
        return True if session.get('user_id') in Config.PROFIREADER_ADMINS else False

    # def service_build(self):
    #     """ This method is helpful when you want to use google_api_client.
    #         Return authorized service """
    #     http = GoogleToken.get_authorize_http()
    #     service = discovery.build(self.google_service_name, self.google_service_version,
    #                               http=http)
    #     return service

class YoutubeApi(GoogleAuthorize):
    """ Use this class for upload videos, get videos, create channels.
        To udpload videos body should be dict like this:
        {
         "title": "My video title",
         "description": "This is a description of my video",
         "tags": ["profireader", "video", "more keywords"],
         "categoryId": 22
         "status": "public"
         }
         Video will uploaded via chunks .You should, pass chunk info (dict) to constructor like:
         chunk_size = 10240 (in bytes) must be multiple 256kb, chunk_number = 0-n (from zero),
         total_size = 1000000
         Requirements : parts = 'snippet' .Pass to this what would you like to return from
          youtube server. (id, snippet, status, contentDetails, fileDetails, player,
          processingDetails, recordingDetails, statistics, suggestions, topicDetails)"""

    def __init__(self, parts=None, video_file=None, body_dict=None, chunk_info=None):
        super(YoutubeApi, self).__init__()
        self.video_file = video_file
        self.body_dict = body_dict
        self.chunk_info = chunk_info
        self.resumable = True if self.chunk_info else False
        self.parts = parts
        # self.youtube = self.service_build()
        self.start_session = Config.YOUTUBE_API['UPLOAD']['SEND_URI']

    def make_body_for_start_upload(self):
        """ make body to create request. category_id default 22, status default 'public'. """

        body = dict(snippet=dict(
                    title=self.body_dict.get('title') or '',
                    description=self.body_dict.get('description') or '',
                    tags=self.body_dict.get('tags'),
                    categoryId=self.body_dict.get('category_id') or 22),
                    status=dict(
                    privacyStatus=self.body_dict.get('status') or 'public'))
        return body

    def make_headers_for_start_upload(self, content_length):
        """ This method make headers for preupload request to get url for upload binary data.
         content_length should be body length in bytes. First step to start upload """
        authorization = GoogleToken.get_credentials_from_db().access_token
        session['authorization'] = authorization
        headers = {'authorization': 'Bearer {0}'.format(authorization),
                   'content-type': 'application/json; charset=utf-8',
                   'content-length': content_length,
                   'x-upload-content-length': self.chunk_info.get('total_size'),
                   'x-upload-content-type': 'application/octet-stream'}

        return headers

    def make_encoded_url(self, body_keys):
        """ This method make values of header url encoded.
         body_keys are values which you want to return from youtube server """
        values = parse.urlencode(dict(uploadType='resumable', part=",".join(body_keys)))
        url_encoded = self.start_session % values
        return url_encoded

    def set_youtube_service_url_to_session(self):

        """ This method add to flask session video_id from youtube server and url for upload
         videos. If raise except - bad credentials """
        body = self.make_body_for_start_upload()
        url = self.make_encoded_url(body.keys())
        body = json.dumps(body).encode('utf8')
        headers = self.make_headers_for_start_upload(sys.getsizeof(body))
        try:
            r = req.Request(url=url, headers=headers,  method='POST')
            response = req.urlopen(r, data=body)
            session['video_id'] = response.headers.get('X-Goog-Correlation-Id')
            session['url'] = response.headers.get('Location')
        except response_code as e:
            print(e.headers)
            print(e.code)

    def make_headers_for_upload(self):
        """ This method make headers for upload videos. Second  step to start upload """
        headers = {'authorization': 'Bearer {0}'.format(session.get('access_token')),
                   'content-type': 'application/octet-stream',
                   'content-length': self.chunk_info.get('chunk_size'),
                   'content-range': 'bytes 0-{0}/{1}'.format(
                       self.chunk_info.get('chunk_size')-1, self.chunk_info.get('total_size'))}
        return headers

    def make_headers_for_resumable_upload(self):
        """ This method make headers for resumable upload videos. Thirst  step to start upload """
        video = db(YoutubeVideo, video_id=session['video_id']).one()
        last_byte = self.chunk_info.get('chunk_size') + video.size - 1
        last_byte = self.chunk_info.get('total_size') - 1 if (self.chunk_info.get(
            'chunk_size') + video.size - 1) > self.chunk_info.get('total_size') else last_byte
        headers = {'authorization': 'Bearer {0}'.format(video.authorization),
                   'content-type': 'application/octet-stream',
                   'content-length': self.chunk_info.get('total_size')-video.size - 1,
                   'content-range': 'bytes {0}-{1}/{2}'.format(video.size,
                                                               last_byte,
                                                               self.chunk_info.get('total_size'))}
        return headers

    def check_upload_status(self):
        """ You can use this method to check upload status. If except you will get error
        code from youtube server """
        headers = {'authorization': 'Bearer {0}'.format(session.get('access_token')),
                   'content-range': 'bytes */{0}'.format(self.chunk_info.get('total_size')),
                   'content-length': 0}
        r = req.Request(url=session['url'], headers=headers,  method='PUT')
        try:
            response = req.urlopen(r)
            return response
        except response_code as e:
            print(e.code)

    def upload(self, video_id=None):

        """ Use this method for upload videos. If video_id you can get from session['video_id'].
          If except error 308 - video has not yet been uploaded, pass next chunk.
          If chunk > 0 run resumable_upload method. If video was uploaded return success """
        chunk_number = self.chunk_info.get('chunk_number')
        if not chunk_number:
            self.set_youtube_service_url_to_session()
        headers = self.make_headers_for_upload()
        try:
            if not chunk_number:
                r = req.Request(url=session['url'], headers=headers, method='PUT')
                response = req.urlopen(r, data=self.video_file,)

                if response.code == 200:
                    youtube = YoutubeVideo(authorization=session['authorization'].split(' ')[-1],
                                           size=self.chunk_info.get('total_size'),
                                           user_id=g.user_dict['id'],
                                           video_id=session['video_id'])
                    youtube.save()
                    return 'success'
        except response_code as e:
            if e.code == 308 and not chunk_number:
                youtube = YoutubeVideo(authorization=session['authorization'].split(' ')[-1],
                                       size=int(e.headers.get('Range').split('-')[-1])+1,
                                       user_id=g.user_dict['id'],
                                       video_id=session['video_id'])
                youtube.save()
                db(YoutubeVideo, video_id=video_id).update({'size': int(e.headers.get(
                                                            'Range').split('-')[-1])+1})
        if chunk_number:
            return self.resumable_upload(video_id)

    def resumable_upload(self, video_id):
        """ This method is useful when you upload video via chunks. Pass video_id from youtube
         server. """
        session['video_id'] = video_id
        headers = self.make_headers_for_resumable_upload()
        r = req.Request(url=session['url'], headers=headers, method='PUT')

        try:
            response = req.urlopen(r, data=self.video_file)
            if response.code == 200 or response.code == 201:
                db(YoutubeVideo, video_id=video_id).update(
                    {'size': self.chunk_info.get('total_size'),
                     'status': 'uploaded'})
                return 'success'
        except response_code as e:
            if e.code == 308:
                db(YoutubeVideo, video_id=video_id).update({'size': int(e.headers.get(
                                                            'Range').split('-')[-1])+1})


class YoutubeVideo(Base, PRBase):
    """ This class make models for youtube videos.
     status video should be 'uploading' or 'uploaded' """
    __tablename__ = 'youtube_video'
    id = Column(TABLE_TYPES['id_profireader'], nullable=False, primary_key=True)
    video_id = Column(TABLE_TYPES['string_30'])
    title = Column(TABLE_TYPES['name'], default='Title')
    authorization = Column(TABLE_TYPES['token'])
    size = Column(TABLE_TYPES['bigint'])
    user_id = Column(TABLE_TYPES['id_profireader'], ForeignKey('user.id'))
    status = Column(TABLE_TYPES['string_30'], default='uploading')

    def __init__(self, title='Title', authorization=None, size=None, user_id=None, video_id=None,
                 status='uploading'):
        super(YoutubeVideo, self).__init__()
        self.title = title
        self.authorization = authorization
        self.size = size
        self.user_id = user_id
        self.video_id = video_id
        self.status = status
