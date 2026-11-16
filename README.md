# Sonoff MINIR4 com HomeKit nativo

Exploratório para controlar a iluminação pelo app Casa na mesma rede Wi-Fi,
com HomeKit executando no próprio MINIR4. O controle local validado não usa
Home Assistant, Homebridge nem um computador permanentemente ligado.

**Estado em 15/11/2026:** protótipo 0.2.2 pareado e confirmado em um MINIR4
ESP32 clássico com Sonoff original 1.2.0. Ligar/desligar pelo Casa e pelo
interruptor físico funcionaram, com estado sincronizado. Retorno ao original
por Wi-Fi e reinstalação do mesmo candidato preservaram o pareamento.
O modo confirmado remove o temporizador de teste e seleciona HomeKit para
os próximos boots. Em 16/11/2026, o usuário confirmou reconexão e estado
correto no Casa após um corte real de energia, sem novo pareamento.
Atualização para outra versão e estabilidade prolongada ainda não foram testadas.

## Escopo e limites

Este é um protótipo experimental, específico para o layout verificado neste
projeto; não é um instalador universal de MINIR4 ou de outros Sonoff. O caminho
ensaiado usa somente Wi-Fi, mas **a primeira OTA sobrescreve o slot inativo
antes do backup integral**. Uma falha anterior a `app_main` não é coberta pelo
retorno implementado. Os ensaios foram feitos em carga de iluminação.

O firmware original fica em `ota_1`; o protótipo ocupa `ota_0`. A aplicação
confere o original por hash antes de selecioná-lo. Não grava eFuses, tabela de
partições ou bootloader. Usa a região `reserve` de 16 KB para os dados HomeKit,
com validação de propriedade e falha sem apagar em caso de erro.

O controle demonstrado é local. A instalação/atualização depende
temporariamente do Mac, da LAN e da nuvem eWeLink. Enquanto HomeKit executa,
o aplicativo eWeLink não controla o módulo; essa função volta com o original.
Não foi validado acesso remoto pelo Casa nem automações com uma central Apple.

## Preparar o código

```sh
git clone https://github.com/TiagoBani/sonoff-minir4.git
cd sonoff-minir4
git clone https://github.com/adamsthws/firmware-liberator.git firmware-liberator
git -C firmware-liberator checkout --detach 77702d7c8b725b85f54a0ae834e6379c9fd93e22
git clone https://github.com/espressif/esp-homekit-sdk.git esp-homekit-reference
git -C esp-homekit-reference checkout --detach 2985547b3ebb99e1e31350d369bc543327fe7e49
python3.11 -m venv .venv-build
.venv-build/bin/pip install -r requirements-build.txt
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
cp target.example.json target.local.json
cp .env.example .env
chmod 600 .env target.local.json
.venv/bin/python prepare_local_access.py
.venv/bin/python prepare_homekit_pairing.py
```

Preencha `target.local.json` com o IP, ID e MAC do seu próprio módulo, e `.env`
com sua conta/região eWeLink. Os valores no exemplo são fictícios. Não envie
credenciais, chaves ou arquivos privados ao repositório. Os geradores criam
material novo por instalação e preservam o que já existe. Guarde o código de
pareamento de `homekit-plan/pairing.local.json` para uso no Casa.

Referências locais ignoradas pelo Git, com revisões fixadas: Firmware Liberator `77702d7c8b725b85f54a0ae834e6379c9fd93e22`
e Espressif HomeKit SDK `2985547b3ebb99e1e31350d369bc543327fe7e49`.
As pastas `firmware-liberator/`, `esp-homekit-reference/` e `haa-reference/`
ficam no `.gitignore`. O HAA é uma referência opcional e não participa deste build.

## Compilar e testar

Pré-requisitos dos testes: Python, compilador Clang, clones locais nas revisões indicadas
e toolchain IDF obtida pelo build (usada pelo parser NVS oficial).
Não precisam de dispositivo nem de credenciais para a suíte abaixo:

```sh
PATH="$PWD/build-tools:$PATH" PLATFORMIO_CORE_DIR="$PWD/.platformio-minir4" .venv-build/bin/pio run -d minir4-homekit -e minir4-homekit
.venv/bin/python -m unittest discover -q
```

O build validado usa PlatformIO 6.1.18, espressif32 6.9.0 e ESP-IDF 5.3.1.
A primeira compilação baixa toolchain e dependências. `build-tools/git` adapta
a chamada Git do CMake Intel para Apple Silicon; em outros sistemas usa Git normal.
Os testes verificam parser, embalagem, NVS, limites de escrita, falhas de
armazenamento, manutenção autenticada e ciclo de confirmação. Não substituem
ensaios no hardware. Os 81 testes existentes passaram antes da publicação.

Não execute `pio upload`. Somente o aplicativo deve ser embalado no formato
OTA proprietário; não grave `bootloader.bin`, `partitions.bin` ou dados OTA
iniciais. O binário compilado contém segredos e **não deve ser publicado**.

## Operar um protótipo já instalado

```sh
.venv/bin/python sonoff_homekit_ctl.py status
.venv/bin/python sonoff_homekit_ctl.py return
```

`status` é leitura autenticada. `return` solicita volta ao original; confirme
o resultado na LAN antes de qualquer OTA. O modo inicial é teste de 20 minutos.
`commit` só é aceito após pareamento e comandos ligar/desligar pelo Casa,
com armazenamento saudável. É uma ação explícita, vinculada ao hash da imagem.

Para atualizar: voltar ao original, confirmar identidade/versão, instalar um
candidato revisado somente em `ota_0`, testar e confirmar novamente. Não usar
OTA Sonoff enquanto HomeKit estiver executando: isso poderia apontar para o
slot onde o original está preservado. Não existe atualizador OTA HomeKit.

O instalador `sonoff_minir4_install.py` exige `--homekit-trial`, hash explícito,
preflight autenticado e `--install` para enviar atualização. Empacotamento exige
um firmware oficial obtido separadamente e um perfil de partições conferido.
Este repositório publica fontes e ferramentas; não inclui imagens prontas,
backups, conta eWeLink ou configuração de um dispositivo real.

## Organização e licenças

- `minir4-homekit/`: aplicativo HomeKit, armazenamento e retorno.
- `minir4-readout/`: auxiliar de leitura de flash/eFuse e parser Wi-Fi.
- `sonoff_*.py`: inspeção, embalagem, instalação e manutenção.
- `tests_homekit/` e `test_*.py`: testes offline com dados fictícios.
- [Arquitetura](homekit-plan/ARQUITETURA.md) e [resultado real](docs/RESULTADO_0_2_2.md).
- [Preservação das chaves e preparação de outros módulos](docs/CHAVES_E_MODULOS.md).
- [Licenças e origem](LICENSES.md): código adaptado preserva GPL-3.0-or-later;
  dependências mantêm suas licenças. A licença MIT inicial não substitui esses avisos.

O repositório público permite consulta e forks. Publicação na branch principal
exige permissão de escrita concedida pelo proprietário; visibilidade pública
não concede essa permissão. Não são incluídos mecanismos para conceder acesso.
