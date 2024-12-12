import base64
import json
import logging
import os
import threading

from flask import Flask
from flask import jsonify
from flask import request
from kubernetes import client
from kubernetes import config
from kubernetes import watch
# import requests

app = Flask(__name__)

# Define the user and cluster role to be bound in each new namespace
USER_NAME = os.getenv('USER_NAME', 'developer')
CLUSTER_ROLE = os.getenv('CLUSTER_ROLE', 'admin')
OPERATOR_THREAD = False
LOG_LEVEL = logging.getLevelNamesMapping(
)[os.getenv('LOG_LEVEL', 'INFO').upper()]

app.logger.setLevel(LOG_LEVEL)

config.load_incluster_config()
v1 = client.CoreV1Api()
namespaces_watcher = watch.Watch()


class operatorClass:

    def __init__(self):
        self.thread = threading.Thread(target=self.run, args=())
        self.thread.daemon = True                       # Daemonize thread
        self.thread.start()                             # Start the execution

    def is_alive(self):
        return self.thread.is_alive()

    def run(self):
        app.logger.info('OPERATOR: starting event watch loop')
        for event in namespaces_watcher.stream(v1.list_namespace, watch=True):
            if event['type'] == 'ADDED':
                namespace = event['object']
                namespace_name = namespace.metadata.name
                try:
                    namespace_admin = namespace.metadata.annotations['com.comet/ns-admin']
                except (TypeError, KeyError):
                    namespace_admin = None
                if namespace_admin == USER_NAME:
                    create_or_update_rolebinding(namespace_name, USER_NAME)
                    app.logger.info(
                        f'OPERATOR: rolebinding for {namespace_name} has been updated',
                    )


@app.route('/', methods=['GET'])
def healthcheck():
    global OPERATOR_THREAD
    if not OPERATOR_THREAD or not OPERATOR_THREAD.is_alive():
        OPERATOR_THREAD = operatorClass()
        app.logger.info('OPERATOR: start operator thread')
    return jsonify({'status': 'Healthy Server'})


@app.route('/mutate', methods=['POST', 'DELETE'])
def mutate():
    admission_review = request.get_json()
    userInfo = admission_review['request']['userInfo']
    namespace = admission_review['request']['namespace']
    sessionName = userInfo['extra']['sessionName'][0]
    validNamespace = namespace.startswith(
        'dev-',
    ) or namespace.startswith(f'{sessionName}-')

    if admission_review['request']['kind']['kind'] == 'Namespace' and userInfo['username'] == USER_NAME:
        if validNamespace:
            match admission_review['request']['operation']:
                case 'CREATE':
                    patch = [
                        {
                            'op': 'add',
                            'path': '/metadata/annotations',
                            'value': {
                                'com.comet/ns-admin': USER_NAME,
                                'com.comet/ns-creator': sessionName,
                            },
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
                case 'DELETE':
                    try:
                        creator = admission_review['request']['oldObject']['metadata']['annotations']['com.comet/ns-creator']
                    except KeyError:
                        creator = None
                    if sessionName == creator:
                        response = {
                            'apiVersion': 'admission.k8s.io/v1',
                            'kind': 'AdmissionReview',
                            'response': {
                                'uid': admission_review['request']['uid'],
                                'allowed': True,
                            },
                        }
                    else:
                        response = {
                            'apiVersion': 'admission.k8s.io/v1',
                            'kind': 'AdmissionReview',
                            'response': {
                                'uid': admission_review['request']['uid'],
                                'allowed': False,
                                'status': {
                                    'code': 403,
                                    'message': f'You ({sessionName}) is not the owner ({creator}) of namespace {namespace}',
                                },
                            },
                        }
        else:
            response = {
                'apiVersion': 'admission.k8s.io/v1',
                'kind': 'AdmissionReview',
                'response': {
                    'uid': admission_review['request']['uid'],
                    'allowed': False,
                    'status': {
                        'code': 403,
                        'message': f'namespace {namespace} is not allowed for {USER_NAME}/{sessionName}. please use prefix "dev-" or "{sessionName}-"',
                    },
                },
            }
        app.logger.info(
            f'ADMISSION_CONTROLLER: namespace={namespace} operation={admission_review['request']['operation']} allowed={response['response']['allowed']} user={USER_NAME}/{sessionName}',
        )
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
