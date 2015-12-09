from flask import render_template, request
from .blueprints_declaration import tools_bp
from .request_wrapers import ok
from ..models.translate import TranslateTemplate


@tools_bp.route('/translate/', methods=['POST'])
@ok
def translate(json):
    translation = TranslateTemplate.getTranslate(request.json['template'], request.json['phrase'])
    return {'phrase': translation}


@tools_bp.route('/save_translate/', methods=['POST'])
@ok
def save_translate(json):
    return TranslateTemplate.getTranslate(request.json['template'], request.json['phrase'], request.json['url'])


@tools_bp.route('/update_last_accessed/', methods=['POST'])
@ok
def update_last_accessed(json):
    return TranslateTemplate.update_last_accessed(json['template'], json['phrase'])

