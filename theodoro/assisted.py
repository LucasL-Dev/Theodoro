import hashlib
import json
import re
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

from playwright.sync_api import Error

from .daily import LABELS

STEPS = {
    'ifood': {
        'ready': 'Marcador da tela inicial autenticada',
        'open': 'Adicionar clique de navegação',
        'store': 'Estabelecimento ativo (fixar seleção atual)',
        'sale_date': 'Filtro de data das vendas',
        'receipt_date': 'Filtro de data dos recebimentos',
        'query': 'Botão de consulta',
        'confirmed_sale_date': 'Data das vendas no resultado',
        'confirmed_receipt_date': 'Data dos recebimentos no resultado',
        **{f'totals.{key}': label for key, label in LABELS.items()},
    },
    'premier': {
        'ready': 'Marcador da tela inicial autenticada',
        'open': 'Adicionar clique de navegação',
        'form': 'Marcador do formulário de lançamento',
        'fields.sale_date': 'Campo de data da venda',
        'fields.competence_date': 'Campo de data da competência',
        'fields.receipt_date': 'Campo de data do recebimento',
        **{f'fields.{key}': f'Campo de {label.lower()}' for key, label in LABELS.items()},
    },
}

PICK = """() => {
  window.__theodoroCancelPick?.();
  const highlight = document.createElement('style');
  highlight.textContent = '*:hover { outline: 2px solid #2684ff !important; }';
  document.documentElement.append(highlight);
  const clean = () => {
    highlight.remove();
    window.removeEventListener('click', pick, true);
    window.removeEventListener('keydown', keyboard, true);
  };
  const finish = (value) => {
    clean();
    window.__theodoroSelection = value;
  };
  const keyboard = (event) => { if (event.key === 'Escape') finish(''); };
  const pick = (event) => {
    event.preventDefault();
    event.stopImmediatePropagation();
    const element = event.target.closest('button,a,input,select,textarea,[role=button]') || event.target;
    if (element.closest('form')?.querySelector('input[type=password]') ||
        element.matches('input[type=password],input[autocomplete=one-time-code]')) {
      finish('');
      return;
    }
    const path = [];
    for (let node = element; node && node !== document.documentElement; node = node.parentElement) {
      const tag = node.localName;
      if (!/^[a-z][a-z0-9-]*$/.test(tag)) { finish(''); return; }
      const siblings = [...node.parentElement.children].filter(child => child.localName === tag);
      path.unshift(siblings.length === 1 ? tag : tag + ':nth-of-type(' + (siblings.indexOf(node) + 1) + ')');
    }
    const selector = 'html > ' + path.join(' > ');
    finish(document.querySelectorAll(selector).length === 1 ? selector : '');
  };
  window.__theodoroSelection = null;
  window.__theodoroCancelPick = clean;
  window.addEventListener('click', pick, true);
  window.addEventListener('keydown', keyboard, true);
}"""

SAFE_NAVIGATION = """element => {
  const control = element.closest('a,button,[role=button],[role=menuitem],input') || element;
  return !control.closest('form') &&
    !control.matches('input,[type=submit],[type=reset]') &&
    !/salvar|gravar|excluir|enviar|confirmar|finalizar|save|submit|delete/i.test(control.textContent);
}"""

SAFE_FIELD = """element => element.matches(
  'input:not([type]),input[type=text],input[type=number],input[type=date],textarea'
) && !element.closest('form')?.querySelector('input[type=password]') &&
  !element.matches('[autocomplete=one-time-code]')"""


def store_digest(value):
    return hashlib.sha256(' '.join(value.split()).casefold().encode()).hexdigest()


def display_value(locator):
    return locator.evaluate("""element => element.matches('select')
      ? element.selectedOptions[0]?.textContent?.trim() || ''
      : (element.matches('input') ? element.value : element.innerText).trim()""")


def save_profile(path, profile):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        temporary.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def set_step(profile, portal, key, selector, fingerprint=None):
    spec = profile.setdefault(portal, {})
    if key == 'open':
        spec.setdefault('open', []).append(selector)
    elif '.' in key:
        group, name = key.split('.')
        spec.setdefault(group, {})[name] = selector
    else:
        spec[key] = selector
    if key == 'store':
        spec['store_digest'] = fingerprint


def scope_step(profile, portal, key):
    spec = profile.get(portal, {})
    if '.' in key:
        group, name = key.split('.')
        return spec.get(group, {}).get(name)
    return spec.get(key)


def validate_profile(profile):
    for portal, steps in STEPS.items():
        for key, label in steps.items():
            if key.startswith('fields.'):
                continue
            if not scope_step(profile, portal, key):
                raise ValueError(f'{portal}: configure {label.lower()}.')
    if not profile['ifood'].get('store_digest'):
        raise ValueError('iFood: fixe o estabelecimento autorizado na configuração.')
    if not profile['premier'].get('fields'):
        raise ValueError('Premier: mapeie os campos obrigatórios do formulário.')
    if profile['premier'].get('allow_unsaved_fill') is not True:
        raise ValueError('Premier: confirme que o formulário não grava ao digitar ou sair do campo.')


@contextmanager
def named_step(label):
    try:
        yield
    except Error as error:
        raise ValueError(f'{label}: controle ausente, ambíguo ou indisponível. Recapture-o em Configurar automação.') from error


def amount_text(value):
    value = value.removeprefix('R$').strip()
    if re.fullmatch(r'[+-]?\d{1,3}(?:\.\d{3})+,\d{2}', value):
        value = value.replace('.', '')
    return value
