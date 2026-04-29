import yaml
import copy

def generate_override(input_file='docker-compose.yml', output_file='docker-compose.override.yml'):
    # Use 'utf-8-sig' to automatically remove the invisible BOM characters
    with open(input_file, 'r', encoding='utf-8-sig') as f:
        compose_data = yaml.safe_load(f)

    override_data = copy.deepcopy(compose_data)

    for service_name, config in override_data.get('services', {}).items():
        # Only target our own services (those hosted on ghcr.io)
        # Skip official/third-party images like mongo, keycloak (quay.io), etc.
        if 'image' in config and isinstance(config['image'], str) and 'ghcr.io' in config['image']:
            print(f"Switching {service_name} to local build (found ghcr.io image)")
            del config['image']
            
            # If the service already specifies a build block (e.g. frontend), leave it alone.
            # Otherwise, tell docker-compose to build from the local directory.
            if 'build' not in config:
                config['build'] = '.'
        else:
            print(f"Skipping {service_name} (using external image or no image)")

    # Tell PyYAML to write an empty string instead of 'null'
    yaml.SafeDumper.add_representer(
        type(None),
        lambda dumper, value: dumper.represent_scalar(u'tag:yaml.org,2002:null', u'')
    )

    with open(output_file, 'w', encoding='utf-8') as f:
        yaml.safe_dump(override_data, f, default_flow_style=False, sort_keys=False)

    print(f"Successfully generated {output_file}")

if __name__ == '__main__':
    generate_override()
 