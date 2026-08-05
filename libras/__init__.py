"""Tradutor embarcado de LIBRAS — PCS3732, Laboratório de Processadores
(Escola Politécnica da USP).

Pipeline de dutos e filtros (Seção 3.1 da documentação):

    B1 captura -> B2 pré-processamento -> B3 landmarks -> B4 classificador
    -> B5 lógica temporal -> (B6 servidor, B7 frontend, B8 voz)

Esta versão contém os blocos B1 a B8: o núcleo do pipeline, o servidor de
aplicação, o frontend web e a síntese de voz. O módulo transversal de
monitoramento do processador (RF-07) entra na entrega seguinte.
"""

__version__ = "1.2"
