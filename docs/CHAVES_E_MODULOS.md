# Chaves e perfis por módulo

Cada módulo precisa de um perfil próprio. Gerar o próximo perfil não deve
substituir o material do aparelho que já está funcionando.

## O que preservar

| Material | Arquivo ou localização | Finalidade |
|---|---|---|
| Código de configuração Casa, setup ID e salt | pairing.local.json | Adicionar o acessório ao Casa |
| Salt/verifier e setup ID compilados | pairing.local.h | Reconstruir a imagem com a mesma configuração de setup |
| Token de manutenção e senha do AP | access.local.h | Manutenção e recuperação pela rede |
| IP, ID e MAC do alvo | target.local.json | Conferir o módulo antes de operar |
| Imagem revisada e manifesto | Perfil privado | Recuperar o candidato exato utilizado |
| Identidade criptográfica do acessório e controladores pareados | NVS reserve do módulo | Preservar exatamente o pareamento em caso de restauração |

O código de oito dígitos não é uma cópia das chaves geradas no pareamento.
Os arquivos de setup permitem reconstruir esse material de configuração,
mas não restauram sozinhos a identidade e os controladores gravados na NVS.
Um backup anterior ao primeiro pareamento não contém o pareamento atual.

## Organização local

Uma pasta por dispositivo em devices-private/, por exemplo:

```text
devices-private/
  luz-exemplo/
    target.local.json
    access.local.h
    pairing.local.json
    pairing.local.h
    firmware-revisado.ota
    manifest.local.json
```

A pasta está no .gitignore. Use diretórios com permissão0700 e arquivos0600,
confira as cópias e preserve os originais. Não publique essa pasta nem o
binário, que contém segredos. A conta eWeLink deve continuar na configuração
local da conta, separada dos perfis de cada dispositivo.

Permissões de arquivo e gitignore não são criptografia. Para cópia durável,
guarde o código e o token em seu cofre de senhas e mantenha o pacote completo
em um backup criptografado separado do repositório. Não guarde a chave de
descriptografia junto do arquivo que ela protege.

Uma cópia atual da NVS pareada precisa de uma etapa específica de leitura do
dispositivo. O perfil de arquivos locais não comprova essa cópia; não
interromper um módulo funcionando apenas para presumir que o backup está completo.

## Próximos módulos

1. Identificar modelo, firmware, ID/MAC e a carga controlada.
2. Validar compatibilidade e layout antes de aplicar o caminho MINIR4.
3. Preparar credenciais, nome e identificação próprios; preservar o perfil anterior.
4. Compilar e revisar um candidato específico. Não reutilizar o binário do piloto.
5. Fazer o ensaio por Wi-Fi e salvar o backup obtido, lembrando que a primeira
   gravação sobrescreve o slot inativo antes da cópia integral.
6. Parear e testar Casa, interruptor físico, retorno e persistência.
7. Confirmar explicitamente apenas depois dos testes.

Mesmo o modelo/firmware nominal igual exige verificar a unidade. Outros
modelos, como BASICR2, não herdam automaticamente o layout e o procedimento
do MINIR4. Módulos offline devem ser reconectados antes do preflight.
