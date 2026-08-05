"""RNF-05 — Privacidade.

Verificação do documento de requisitos: "Mesmo teste de isolamento de rede do
RNF-04; inspeção do código quanto a chamadas de saída." Nenhum quadro,
landmark ou texto traduzido deixa o dispositivo, e não há telemetria nem
gravação de vídeo.

A inspeção é feita por AST, e não por leitura: é o que continua valendo
quando alguém adicionar um módulo novo ao pacote.
"""
import ast
from pathlib import Path

import libras
from libras.demo import make_demo_components
from libras.pipeline import PipelineState, TranslationPipeline

PACKAGE_DIR = Path(libras.__file__).resolve().parent
NETWORK_MODULES = {"urllib", "http", "requests", "socket", "ftplib",
                   "smtplib", "telnetlib", "xmlrpc"}
# get_model baixa o modelo do MediaPipe uma única vez, sob comando explícito
# do usuário (`python -m libras.get_model`): é entrada de dados, não saída, e
# não participa da execução do tradutor.
NETWORK_ALLOWED = {"get_model.py"}
# server expõe HTTP na rede local — é o servidor de aplicação (B6), que
# responde a requisições, mas não as origina.
SERVER = "server.py"


def imported_modules(tree: ast.Module) -> set:
    """Todos os nomes de módulo importados no arquivo, em qualquer nível."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_nenhum_modulo_de_execucao_importa_rede():
    """Só get_model e o próprio servidor podem falar de rede."""
    offenders = {}
    for source_file in sorted(PACKAGE_DIR.glob("*.py")):
        if source_file.name in NETWORK_ALLOWED | {SERVER}:
            continue
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        used = imported_modules(tree) & NETWORK_MODULES
        if used:
            offenders[source_file.name] = used
    assert not offenders, f"módulos com acesso a rede: {offenders}"


def test_servidor_nao_origina_requisicoes():
    """O B6 responde requisições; não faz nenhuma. Flask/urllib de saída no
    servidor seria vazamento de vídeo ou de tradução."""
    tree = ast.parse((PACKAGE_DIR / SERVER).read_text(encoding="utf-8"))
    assert not imported_modules(tree) & (NETWORK_MODULES - {"http"})


def test_nenhum_quadro_e_gravado_em_disco(fast_config, tmp_path,
                                          monkeypatch):
    """Execução do pipeline não deixa arquivo algum atrás de si."""
    monkeypatch.chdir(tmp_path)
    source, extractor, classifier = make_demo_components(fast_config)
    pipeline = TranslationPipeline(source, extractor, classifier, fast_config,
                                   state=PipelineState())
    for _ in range(60):
        pipeline.step()

    assert list(tmp_path.iterdir()) == [], \
        f"o pipeline escreveu em disco: {list(tmp_path.iterdir())}"


def test_quadro_fica_apenas_em_memoria_e_e_substituido(fast_config):
    """O último quadro é mantido só para exibição, e sobrescrito a cada
    passo: não há acúmulo de vídeo no processo."""
    source, extractor, classifier = make_demo_components(fast_config)
    pipeline = TranslationPipeline(source, extractor, classifier, fast_config,
                                   state=PipelineState())
    pipeline.step()
    first = pipeline.latest_frame()
    pipeline.step()
    assert first is not pipeline.latest_frame()


def test_estado_publicado_nao_contem_video_nem_landmarks(fast_config):
    """O que a API expõe é texto e números — nunca o quadro ou os 21 pontos
    da mão."""
    source, extractor, classifier = make_demo_components(fast_config)
    state = PipelineState()
    pipeline = TranslationPipeline(source, extractor, classifier, fast_config,
                                   state=state)
    for _ in range(30):
        pipeline.step()

    snapshot = state.to_dict()
    assert set(snapshot) == {"letra_atual", "confianca", "mao_presente",
                             "palavra_parcial", "ultima_palavra", "historico",
                             "fps", "quadros_processados", "latencia_ms"}
