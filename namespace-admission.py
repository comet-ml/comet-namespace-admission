import base64
import json
import logging
import threading

from flask import Flask
from flask import jsonify
from flask import request
from kubernetes import client
from kubernetes import config
from kubernetes import watch
# import requests

app = Flask(__name__)
app.logger.setLevel(logging.DEBUG)

# Define the user and cluster role to be bound in each new namespace
USER_NAME = 'developer'
GROUP_NAME = 'developers'
CLUSTER_ROLE = 'admin'
OPERATOR_STARTED = False

config.load_incluster_config()
v1 = client.CoreV1Api()
namespaces_watcher = watch.Watch()


class operatorClass:

    def __init__(self):
        thread = threading.Thread(target=self.run, args=())
        thread.daemon = True                       # Daemonize thread
        thread.start()                             # Start the execution

    def run(self):
        app.logger.debug('starting event watch loop')
        for event in namespaces_watcher.stream(v1.list_namespace, watch=True):
            # TODO: update only namespaces with correct annotation
            app.logger.debug(f'OPERATOR {event}')

            # if event['type'] == 'ADDED':
            #     namespace = event['object']
            #     namespace_name = namespace.metadata.name
            #     create_or_update_rolebinding(namespace_name, USER_NAME)


@app.route('/', methods=['GET'])
def healthcheck():
    global OPERATOR_STARTED
    if not OPERATOR_STARTED:
        begin = operatorClass()
        app.logger.debug(begin)
        OPERATOR_STARTED = True
    return jsonify({'status': 'Healthy Server'})


@app.route('/mutate', methods=['POST'])
def mutate():
    admission_review = request.get_json()
    # Check if the request is for a new namespace creation
    if admission_review['request']['kind']['kind'] == 'Namespace':
        app.logger.debug(f'ADMISSION_REVIEW {admission_review}')

        patch = [
            {
                'op': 'add',
                'path': '/metadata/annotations',
                'value': {'com.comet/ns-admin': USER_NAME},
            },
        ]

        response = {
            'apiVersion': 'admission.k8s.io/v1',
            'kind': 'AdmissionReview',
            'response': {
                'uid': admission_review['request']['uid'],
                'allowed': True,
                'patchType': 'JSONPatch',
                'patch': base64.b64encode(json.dumps(patch).encode('utf-8')).decode('utf-8'),
            },
        }
        return jsonify(response)

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
            name=CLUSTER_ROLE,
        ),
        subjects=[
            {
                'kind': 'User',
                'name': user,
                'api_group': 'rbac.authorization.k8s.io',
            },
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


if __name__ == '__main__':
    app.run(port=8000)
