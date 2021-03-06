#!/usr/bin/env python
import cPickle as pickle
import logging
import os
import sys
from collections import defaultdict

import eventlet

eventlet.sleep()
eventlet.monkey_patch()

import flask
from flask_socketio import SocketIO, emit
from flask_cors import CORS

from simulation.turn_manager import state_provider
from simulation import map_generator
from simulation.avatar.avatar_manager import AvatarManager
from simulation.turn_manager import ConcurrentTurnManager
from simulation.worker_manager import WORKER_MANAGERS
from simulation.pickups import pickups_update

app = flask.Flask(__name__)
CORS(app, supports_credentials=True)
socketio = SocketIO()

worker_manager = None


def to_cell_type(cell):
    if not cell.habitable:
        return 1
    if cell.generates_score:
        return 2
    return 0


def player_dict(avatar):
    return {
        'id': avatar.player_id,
        'x': avatar.location.x,
        'y': avatar.location.y,
        'health': avatar.health,
        'score': avatar.score,
        'rotation': 0,
        "colours": {
            "bodyStroke": "#0ff",
            "bodyFill": "#%06x" % (avatar.player_id * 4999),
            "eyeStroke": "#aff",
            "eyeFill": "#eff",
        }
    }


def get_game_state():
    with state_provider as game_state:
        world_map = game_state.world_map
        return {
                'era': "less_flat",
                'southWestCorner': world_map.get_serialised_south_west_corner(),
                'northEastCorner': world_map.get_serialised_north_east_corner(),
                'players': game_state.avatar_manager.players_update()['players'],
                'pickups': pickups_update(world_map)['pickups'],
                'scoreLocations': (game_state.world_map.
                                   score_location_update()['scoreLocations']),
                'obstacles': world_map.obstacles_update()['obstacles']
        }


@socketio.on('connect')
def world_update_on_connect():
    emit(
        'game-state',
        get_game_state(),
    )


def send_world_update():
    socketio.emit(
        'game-state',
        get_game_state(),
        broadcast=True,
    )


@app.route('/game-<game_id>')
def healthcheck(game_id):
    return 'HEALTHY'


@app.route('/player/<player_id>')
def player_data(player_id):
    player_id = int(player_id)
    return flask.jsonify({
        'code': worker_manager.get_code(player_id),
        'options': {},       # Game options
        'state': None,
    })


def run_game(port):
    global worker_manager

    print("Running game...")
    settings = pickle.loads(os.environ['settings'])
    api_url = os.environ.get('GAME_API_URL', 'http://localhost:8000/players/api/games/')
    generator = getattr(map_generator, settings['GENERATOR'])(settings)
    player_manager = AvatarManager()
    game_state = generator.get_game_state(player_manager)
    turn_manager = ConcurrentTurnManager(game_state=game_state,
                                         end_turn_callback=send_world_update,
                                         completion_url=api_url+'complete/')
    WorkerManagerClass = WORKER_MANAGERS[os.environ.get('WORKER_MANAGER', 'local')]
    worker_manager = WorkerManagerClass(game_state=game_state,
                                        users_url=api_url,
                                        port=port)
    worker_manager.start()
    turn_manager.start()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    socketio.init_app(app, resource=os.environ.get('SOCKETIO_RESOURCE', 'socket.io'))
    run_game(int(sys.argv[2]))
    socketio.run(
        app,
        debug=False,
        host=sys.argv[1],
        port=int(sys.argv[2]),
        use_reloader=False,
    )
