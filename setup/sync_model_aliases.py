import json
import re
from collections import defaultdict

def load_models():
    with open('models_garage.json', 'r') as f:
        return json.load(f)

def generate_aliases(models_data):
    aliases = {}

    # --- Google ---
    google_models = sorted(list(set(models_data.get('google', []))))
    google_aliases = defaultdict(list)

    for model in google_models:
        # Gemini 2.0
        if 'gemini-2.0-flash' in model:
            if 'lite' in model:
                google_aliases['gemini-2.0-flash-lite'].append(model)
            else:
                google_aliases['gemini-2.0-flash'].append(model)

        # Gemini 2.5 and Latest
        elif 'gemini-2.5-flash' in model or 'gemini-flash-latest' in model:
            if 'lite' in model:
                google_aliases['gemini-2.5-flash-lite'].append(model)
            else:
                google_aliases['gemini-2.5-flash'].append(model)

        elif 'gemini-flash-lite-latest' in model:
             google_aliases['gemini-2.5-flash-lite'].append(model)

        # Gemini Pro
        elif 'gemini-2.5-pro' in model or 'gemini-pro-latest' in model:
             google_aliases['gemini-2.5-pro'].append(model)

        # Gemma 3
        elif 'gemma-3' in model:
            # Extract size: looks like gemma-3-12b-it or gemma-3n-e4b-it
            # Regex: search for digits before 'b'
            size_match = re.search(r'(\d+)b', model)
            if size_match:
                size = int(size_match.group(1))
                if size <= 4:
                    google_aliases['gemma-tiny'].append(model)
                else:
                    google_aliases['gemma'].append(model)
            else:
                # Fallback if pattern doesn't match
                google_aliases['gemma'].append(model)

        # Other
        else:
            google_aliases[model].append(model)

    aliases['google'] = dict(google_aliases)

    # --- Mistral ---
    mistral_models = sorted(list(set(models_data.get('mistral', []))))
    mistral_aliases = defaultdict(list)

    for model in mistral_models:
        parts = model.split('-')
        if len(parts) >= 2:
            prefix = f"{parts[0]}-{parts[1]}"

            if parts[0] == 'open' and parts[1] == 'mistral':
                if len(parts) > 2:
                     if parts[2] == 'nemo':
                         prefix = "open-mistral-nemo"
                     elif parts[2] == '7b':
                         prefix = "open-mistral-7b"

            elif parts[0] == 'mistral' and parts[1] == 'large':
                 if len(parts) > 2 and parts[2] == 'pixtral':
                     prefix = "mistral-large-pixtral"
                 else:
                     prefix = "mistral-large"

            elif parts[0] == 'pixtral':
                 prefix = f"{parts[0]}-{parts[1]}"

            if parts[0] == 'codestral':
                prefix = 'codestral'

            mistral_aliases[prefix].append(model)
        else:
            mistral_aliases[model].append(model)

    aliases['mistral'] = dict(mistral_aliases)

    # --- Groq, Cerebras, Cohere ---
    for provider in ['groq', 'cerebras', 'cohere']:
        p_models = sorted(list(set(models_data.get(provider, []))))
        p_aliases = {}
        for model in p_models:
            # For these, 1-to-1 mapping as per instruction
            p_aliases[model] = [model]
        aliases[provider] = p_aliases

    return aliases

if __name__ == "__main__":
    data = load_models()
    result = generate_aliases(data)

    sorted_result = {}
    for provider in sorted(result.keys()):
        sorted_aliases = {}
        for alias in sorted(result[provider].keys()):
            sorted_aliases[alias] = sorted(result[provider][alias])
        sorted_result[provider] = sorted_aliases

    print(json.dumps(sorted_result, indent=4))
