import json

import requests
from flask import Flask
from flask import jsonify
from flask import request

app = Flask(__name__)

# Define the user and cluster role to be bound in each new namespace
USER_NAME = 'developer'
GROUP_NAME = 'developers'
CLUSTER_ROLE = 'admin'


@app.route('/mutate', methods=['POST'])
def mutate():
    request_info = request.get_json()
    # Check if the request is for a new namespace creation
    if request_info['request']['kind']['kind'] == 'Namespace':
        namespace_name = request_info['request']['object']['metadata']['name']

        # RoleBinding to give admin access to the user in the new namespace
        rolebinding = {
            'apiVersion': 'rbac.authorization.k8s.io/v1',
            'kind': 'RoleBinding',
            'metadata': {
                'name': f"{USER_NAME}-admin",
                'namespace': namespace_name,
            },
            'roleRef': {
                'apiGroup': 'rbac.authorization.k8s.io',
                'kind': 'ClusterRole',
                'name': CLUSTER_ROLE,
            },
            'subjects': [
                {
                    'kind': 'User',
                    'name': USER_NAME,
                    'apiGroup': 'rbac.authorization.k8s.io',
                }, {
                    'kind': 'Group',
                    'name': GROUP_NAME,
                    'apiGroup': 'rbac.authorization.k8s.io',
                },
            ],
        }

        # Patch the namespace creation request to include the RoleBinding
        patch = [
            {
                'op': 'add',
                'path': '/metadata/annotations',
                'value': {'rolebinding': json.dumps(rolebinding)},
            },
        ]

        response = {
            'response': {
                'uid': request_info['request']['uid'],
                'allowed': True,
                'patchType': 'JSONPatch',
                'patch': json.dumps(patch).encode('utf-8').decode('utf-8'),
            },
        }
        return jsonify(response)
    else:
        return jsonify({'response': {'allowed': True}})


if __name__ == '__main__':
    app.run(port=8000)
