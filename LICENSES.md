# Licenças e origem do código

`LICENSE` é a licença MIT existente na criação do repositório e foi preservada.
Ela não relicencia trechos de terceiros nem substitui avisos específicos.

Os aplicativos em `minir4-readout/` e `minir4-homekit/` trazem avisos
`GPL-3.0-or-later`. O auxiliar e o reaproveitamento do Wi-Fi foram adaptados de
adamsthws/firmware-liberator, revisão
77702d7c8b725b85f54a0ae834e6379c9fd93e22 (GPLv3). Os fontes derivados continuam
sob GPL-3.0-or-later; o texto correspondente está em `COPYING` e
`minir4-readout/LICENSE`. Esta publicação não altera esses avisos.

Ferramentas Python, testes e documentação adicionados por este projeto usam a
licença MIT de `LICENSE`, salvo aviso específico no arquivo. Importar ou usar
as ferramentas do clone local não muda a licença do código desse clone local.

O SDK espressif/esp-homekit-sdk é usado como clone local, ignorado pelo Git, na revisão
2985547b3ebb99e1e31350d369bc543327fe7e49. Seus componentes mantêm os avisos
originais, inclusive condições de uso em produtos Espressif. O componente
local de plataforma referencia os fontes originais do SDK e substitui o
backend de armazenamento; não distribui uma cópia relicenciada desses fontes.
ESP-IDF e dependências gerenciadas também mantêm suas próprias licenças.

Firmware proprietário Sonoff, dumps de flash/eFuse, binários com segredos,
chaves, tokens e credenciais não são distribuídos neste repositório.
