"""Tradutor embarcado de LIBRAS — PCS3732, Laboratório de Processadores
(Escola Politécnica da USP).

Pipeline de dutos e filtros (Seção 3.1 da documentação):

    B1 captura -> B2 pré-processamento -> B3 landmarks -> B4 classificador
    -> B5 lógica temporal -> (B6 servidor, B7 frontend, B8 voz)

Esta versão contém os blocos B1 a B8 e o módulo transversal de instrumentação
que alimenta o painel de desempenho (RF-07) e o benchmark (RNF-02/RNF-03). A
execução no alvo e a avaliação comparativa são a entrega seguinte.
"""

__version__ = "1.3"
