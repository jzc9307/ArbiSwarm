"""Small provider schema; strict Pydantic validation remains on the server.

Do not send Pydantic's metadata and nested cardinality constraints directly to
the provider's constrained decoder. The analyst's original schema was rejected
with HTTP 400 even for one offer. Inline local references and require a stable
object shape; enforce all lengths, bounds and evidence checks after generation.
"""
from copy import deepcopy


def provider_schema(model):
    original = model.model_json_schema()

    def project(node, refs=()):
        if not isinstance(node, dict):
            return deepcopy(node)
        if '$ref' in node:
            ref = node['$ref']
            if not ref.startswith('#/') or ref in refs:
                raise ValueError('Only nonrecursive local response-schema references are supported.')
            target = original
            for part in ref[2:].split('/'):
                target = target[part.replace('~1', '/').replace('~0', '~')]
            return project(target, (*refs, ref))
        result = {}
        for key in ('type', 'enum', 'anyOf', 'properties', 'items', 'additionalProperties'):
            if key not in node:
                continue
            value = node[key]
            if key == 'properties':
                result[key] = {name: project(child, refs) for name, child in value.items()}
            elif key == 'anyOf':
                result[key] = [project(child, refs) for child in value]
            elif key in ('items', 'additionalProperties'):
                result[key] = project(value, refs)
            else:
                result[key] = deepcopy(value)
        if 'properties' in result:
            # Defaults remain local; the model explicitly emits [], null, etc.
            result['required'] = list(result['properties'])
        return result

    return project(original)
