import base64
import json
import logging

import requests
from flask import Flask
from flask import jsonify
from flask import request
from kubernetes import client
from kubernetes import config

app = Flask(__name__)
app.logger.setLevel(logging.DEBUG)

# Define the user and cluster role to be bound in each new namespace
USER_NAME = 'developer'
GROUP_NAME = 'developers'
CLUSTER_ROLE = 'admin'

config.load_incluster_config()
app.logger.debug(config)


@app.route('/mutate', methods=['POST'])
def mutate_namespace():
    # Parse AdmissionReview request
    admission_review = request.json

    # Extract the namespace object
    try:
        namespace = admission_review['request']['object']
        namespace_name = namespace['metadata']['name']
        annotations = namespace.get('metadata', {}).get('annotations', {})
        user = annotations.get('rolebinding/user')
    except KeyError as e:
        return create_admission_response(admission_review, allowed=False, message=f"Invalid request structure: {e}")

    if not user:
        # If no relevant annotations, allow request without changes
        return create_admission_response(admission_review, allowed=True)

    # Create or update RoleBinding
    try:
        create_or_update_rolebinding(namespace_name, user)
    except Exception as e:
        return create_admission_response(
            admission_review,
            allowed=False,
            message=f"Failed to create or update RoleBinding: {str(e)}",
        )

    # Allow the namespace creation/update
    return create_admission_response(admission_review, allowed=True)


def create_or_update_rolebinding(namespace, user):
    """Create or update a RoleBinding for the given user in the specified namespace."""
    v1_rbac = client.RbacAuthorizationV1Api()

    role_binding_name = 'namespace-admin'
    role_binding = client.V1RoleBinding(
        metadata=client.V1ObjectMeta(
            name=role_binding_name, namespace=namespace,
        ),
        role_ref=client.V1RoleRef(
            api_group='rbac.authorization.k8s.io',
            kind='ClusterRole',
            name='admin',
        ),
        subjects=[
            client.V1Subject(
                kind='User',
                name=user,
                api_group='rbac.authorization.k8s.io',
            ),
        ],
    )

    try:
        # Attempt to create the RoleBinding
        v1_rbac.create_namespaced_role_binding(namespace, role_binding)
    except client.exceptions.ApiException as e:
        if e.status == 409:  # Conflict means it already exists
            # Update the RoleBinding if it exists
            v1_rbac.replace_namespaced_role_binding(
                role_binding_name, namespace, role_binding,
            )
        else:
            raise


def create_admission_response(admission_review, allowed, message=None):
    """Generate a Kubernetes AdmissionReview response."""
    response = {
        'apiVersion': 'admission.k8s.io/v1',
        'kind': 'AdmissionReview',
        'response': {
            'uid': admission_review['request']['uid'],
            'allowed': allowed,
        },
    }

    if message:
        response['response']['status'] = {
            'code': 403 if not allowed else 200,
            'message': message,
        }

    return jsonify(response)


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
            'apiVersion': 'admission.k8s.io/v1',
            'kind': 'AdmissionReview',
            'response': {
                'uid': request_info['request']['uid'],
                'allowed': True,
                'patchType': 'JSONPatch',
                'patch': base64.b64encode(json.dumps(patch).encode('utf-8')).decode('utf-8'),
            },
        }
        return jsonify(response)
    else:
        return jsonify({'response': {'allowed': True}})


@app.route('/', methods=['GET'])
def healthcheck():
    return jsonify({'status': 'Healthy Server'})


if __name__ == '__main__':
    app.run(port=8000)
