# Auxiliar de leitura MINIR4

Auxiliar ESP-IDF para ESP32 clássico, adaptado de Firmware Liberator
77702d7c8b725b85f54a0ae834e6379c9fd93e22, sob GPL-3.0-or-later (LICENSE).
A versão0.1.2 foi testada por Wi-Fi: flash/eFuse copiados e retorno ao original
1.2.0 confirmado. Não grava eFuses nem fornece rotas de atualização.

A OTA inicial sobrescreve o slot inativo ANTES do backup. A cópia obtida não é
um backup integral anterior à primeira escrita. O original no outro slot é
validado por hash e selecionado para o próximo boot antes de iniciar Wi-Fi.
Falhas anteriores a app_main não são cobertas pelo retorno.

Rotas, todas com X-Access-Token: GET /status, /flash, /flash-sha256, /efuse;
POST /return. Retorna após10min de inatividade autenticada ou20min totais.
Wi-Fi usa RAM e herda configuração Sonoff; AP protegido serve de fallback.

Credenciais são geradas por ../prepare_local_access.py. Nunca publicar o
cabeçalho privado access.local.h, o binário compilado ou os backups.
O parser portátil stock_wifi.c é compartilhado com o projeto HomeKit.

Compilar com PlatformIO6.1.18/espressif32@6.9.0; ver ../README.md. Não executar
pio upload nem gravar tabela/bootloader. Usar somente o aplicativo embalado
no envelope proprietário, com hash revisado e preflight autenticado.
