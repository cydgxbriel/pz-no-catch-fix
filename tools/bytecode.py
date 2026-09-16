#!/usr/bin/env python3
"""
Desmontador de .class, para ler o Java do jogo.

Boa parte do que o mod conserta so da para entender no bytecode: o Lua do PZ e
so a superficie, e a decisao que quebra a pesca em MP esta em
`zombie.core.ActionManager`. O JRE que vem com o jogo e um runtime, nao um JDK
-- nao tem `javap` -- e as afirmacoes de bytecode do README precisam ser
conferiveis por quem le. Daqui sai a evidencia.

Uso:
    .venv/bin/python tools/bytecode.py zombie.core.ActionManager getPlayer
    .venv/bin/python tools/bytecode.py zombie.core.FishingAction getLuaTable
    .venv/bin/python tools/bytecode.py zombie.core.Action --fields
    .venv/bin/python tools/bytecode.py zombie.core.Action --methods

O nome da classe aceita ponto ou barra. Sem o nome do metodo, lista a
assinatura de todos. O filtro de metodo e por substring, entao `update` pega
`update()` e `updateLine()`.

As classes saem direto de `projectzomboid.jar` (via tools/paths.py); um caminho
de arquivo .class tambem serve.
"""
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402


# ---------------------------------------------------------------------------
# Leitura do formato
# ---------------------------------------------------------------------------

class ClassFile:
    """So o suficiente para chegar no bytecode: pool, campos e metodos."""

    def __init__(self, data: bytes):
        self.d, self.p = data, 0
        if self.u4() != 0xCAFEBABE:
            raise ValueError("nao e um .class (falta o magic CAFEBABE)")
        self.minor, self.major = self.u2(), self.u2()
        self.cp = self._pool()
        self.access, self.this, self.sup = self.u2(), self.u2(), self.u2()
        # As interfaces nao interessam, mas os bytes sim. Em duas etapas de
        # proposito: `self.p += 2 * self.u2()` le self.p ANTES de u2() avanca-lo,
        # e o indice fica 2 bytes atras -- os campos entram no lugar dos metodos.
        interfaces = self.u2()
        self.p += 2 * interfaces
        self.fields = self._members()
        self.methods = self._members()

    # leitura crua -----------------------------------------------------------
    def u1(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def u2(self):
        v = struct.unpack_from(">H", self.d, self.p)[0]
        self.p += 2
        return v

    def u4(self):
        v = struct.unpack_from(">I", self.d, self.p)[0]
        self.p += 4
        return v

    # constant pool ----------------------------------------------------------
    def _pool(self):
        n = self.u2()
        cp, i = [None] * n, 1
        while i < n:
            tag = self.u1()
            if tag == 1:
                size = self.u2()
                cp[i] = ("Utf8",
                         self.d[self.p:self.p + size].decode("utf-8", "replace"))
                self.p += size
            elif tag in (7, 8, 16, 19, 20):
                nome = {7: "Class", 8: "String", 16: "MethodType",
                        19: "Module", 20: "Package"}[tag]
                cp[i] = (nome, self.u2())
            elif tag in (9, 10, 11, 12, 17, 18):
                nome = {9: "Fieldref", 10: "Methodref",
                        11: "InterfaceMethodref", 12: "NameAndType",
                        17: "Dynamic", 18: "InvokeDynamic"}[tag]
                cp[i] = (nome, self.u2(), self.u2())
            elif tag == 3:
                cp[i] = ("Integer", struct.unpack_from(">i", self.d, self.p)[0])
                self.p += 4
            elif tag == 4:
                cp[i] = ("Float", struct.unpack_from(">f", self.d, self.p)[0])
                self.p += 4
            elif tag == 5:
                cp[i] = ("Long", struct.unpack_from(">q", self.d, self.p)[0])
                self.p += 8
            elif tag == 6:
                cp[i] = ("Double", struct.unpack_from(">d", self.d, self.p)[0])
                self.p += 8
            elif tag == 15:
                cp[i] = ("MethodHandle", self.u1(), self.u2())
            else:
                raise ValueError(f"tag {tag} desconhecida no offset {self.p}")
            # long e double ocupam DUAS entradas do pool (JVMS 4.4.5)
            i += 2 if tag in (5, 6) else 1
        return cp

    def utf(self, i):
        return self.cp[i][1]

    def classe(self, i):
        return self.utf(self.cp[i][1])

    def const(self, i):
        e = self.cp[i]
        tipo = e[0]
        if tipo == "Utf8":
            return repr(e[1])
        if tipo == "String":
            return repr(self.utf(e[1]))
        if tipo == "Class":
            return self.classe(i)
        if tipo in ("Fieldref", "Methodref", "InterfaceMethodref"):
            nt = self.cp[e[2]]
            return f"{self.classe(e[1])}.{self.utf(nt[1])}:{self.utf(nt[2])}"
        if tipo == "NameAndType":
            return f"{self.utf(e[1])}:{self.utf(e[2])}"
        return f"{tipo} {e[1:]}"

    # membros ----------------------------------------------------------------
    def _attrs(self):
        out = {}
        for _ in range(self.u2()):
            nome, size = self.utf(self.u2()), self.u4()
            out.setdefault(nome, []).append(self.d[self.p:self.p + size])
            self.p += size
        return out

    def _members(self):
        out = []
        for _ in range(self.u2()):
            acc, nome, desc = self.u2(), self.utf(self.u2()), self.utf(self.u2())
            out.append((acc, nome, desc, self._attrs()))
        return out


# ---------------------------------------------------------------------------
# Opcodes
# ---------------------------------------------------------------------------

# (codigo, nome, quantos bytes de operando)
_TABELA = [
    (0, "nop", 0), (1, "aconst_null", 0), (2, "iconst_m1", 0),
    (3, "iconst_0", 0), (4, "iconst_1", 0), (5, "iconst_2", 0),
    (6, "iconst_3", 0), (7, "iconst_4", 0), (8, "iconst_5", 0),
    (9, "lconst_0", 0), (10, "lconst_1", 0), (11, "fconst_0", 0),
    (12, "fconst_1", 0), (13, "fconst_2", 0), (14, "dconst_0", 0),
    (15, "dconst_1", 0), (16, "bipush", 1), (17, "sipush", 2),
    (18, "ldc", 1), (19, "ldc_w", 2), (20, "ldc2_w", 2),
    (21, "iload", 1), (22, "lload", 1), (23, "fload", 1), (24, "dload", 1),
    (25, "aload", 1), (46, "iaload", 0), (47, "laload", 0), (48, "faload", 0),
    (49, "daload", 0), (50, "aaload", 0), (51, "baload", 0), (52, "caload", 0),
    (53, "saload", 0), (54, "istore", 1), (55, "lstore", 1), (56, "fstore", 1),
    (57, "dstore", 1), (58, "astore", 1), (79, "iastore", 0),
    (80, "lastore", 0), (81, "fastore", 0), (82, "dastore", 0),
    (83, "aastore", 0), (84, "bastore", 0), (85, "castore", 0),
    (86, "sastore", 0), (87, "pop", 0), (88, "pop2", 0), (89, "dup", 0),
    (90, "dup_x1", 0), (91, "dup_x2", 0), (92, "dup2", 0), (93, "dup2_x1", 0),
    (94, "dup2_x2", 0), (95, "swap", 0), (96, "iadd", 0), (97, "ladd", 0),
    (98, "fadd", 0), (99, "dadd", 0), (100, "isub", 0), (101, "lsub", 0),
    (102, "fsub", 0), (103, "dsub", 0), (104, "imul", 0), (105, "lmul", 0),
    (106, "fmul", 0), (107, "dmul", 0), (108, "idiv", 0), (109, "ldiv", 0),
    (110, "fdiv", 0), (111, "ddiv", 0), (112, "irem", 0), (113, "lrem", 0),
    (114, "frem", 0), (115, "drem", 0), (116, "ineg", 0), (117, "lneg", 0),
    (118, "fneg", 0), (119, "dneg", 0), (120, "ishl", 0), (121, "lshl", 0),
    (122, "ishr", 0), (123, "lshr", 0), (124, "iushr", 0), (125, "lushr", 0),
    (126, "iand", 0), (127, "land", 0), (128, "ior", 0), (129, "lor", 0),
    (130, "ixor", 0), (131, "lxor", 0), (132, "iinc", 2), (133, "i2l", 0),
    (134, "i2f", 0), (135, "i2d", 0), (136, "l2i", 0), (137, "l2f", 0),
    (138, "l2d", 0), (139, "f2i", 0), (140, "f2l", 0), (141, "f2d", 0),
    (142, "d2i", 0), (143, "d2l", 0), (144, "d2f", 0), (145, "i2b", 0),
    (146, "i2c", 0), (147, "i2s", 0), (148, "lcmp", 0), (149, "fcmpl", 0),
    (150, "fcmpg", 0), (151, "dcmpl", 0), (152, "dcmpg", 0), (153, "ifeq", 2),
    (154, "ifne", 2), (155, "iflt", 2), (156, "ifge", 2), (157, "ifgt", 2),
    (158, "ifle", 2), (159, "if_icmpeq", 2), (160, "if_icmpne", 2),
    (161, "if_icmplt", 2), (162, "if_icmpge", 2), (163, "if_icmpgt", 2),
    (164, "if_icmple", 2), (165, "if_acmpeq", 2), (166, "if_acmpne", 2),
    (167, "goto", 2), (168, "jsr", 2), (169, "ret", 1), (172, "ireturn", 0),
    (173, "lreturn", 0), (174, "freturn", 0), (175, "dreturn", 0),
    (176, "areturn", 0), (177, "return", 0), (178, "getstatic", 2),
    (179, "putstatic", 2), (180, "getfield", 2), (181, "putfield", 2),
    (182, "invokevirtual", 2), (183, "invokespecial", 2),
    (184, "invokestatic", 2), (185, "invokeinterface", 4),
    (186, "invokedynamic", 4), (187, "new", 2), (188, "newarray", 1),
    (189, "anewarray", 2), (190, "arraylength", 0), (191, "athrow", 0),
    (192, "checkcast", 2), (193, "instanceof", 2), (194, "monitorenter", 0),
    (195, "monitorexit", 0), (197, "multianewarray", 3), (198, "ifnull", 2),
    (199, "ifnonnull", 2), (200, "goto_w", 4), (201, "jsr_w", 4),
]
# as formas com indice embutido (iload_0, astore_2, ...)
for base, nome in ((26, "iload"), (30, "lload"), (34, "fload"), (38, "dload"),
                   (42, "aload"), (59, "istore"), (63, "lstore"),
                   (67, "fstore"), (71, "dstore"), (75, "astore")):
    _TABELA += [(base + n, f"{nome}_{n}", 0) for n in range(4)]

OPS = {codigo: (nome, n) for codigo, nome, n in _TABELA}

# operandos que sao indice no constant pool, e valem mais impressos por extenso
REFERENCIA = {
    "ldc_w", "ldc2_w", "getstatic", "putstatic", "getfield", "putfield",
    "invokevirtual", "invokespecial", "invokestatic", "invokeinterface",
    "invokedynamic", "new", "checkcast", "instanceof", "anewarray",
}


def desmontar(cf: ClassFile, code: bytes):
    linhas, p = [], 0
    while p < len(code):
        op, inicio = code[p], p
        p += 1

        if op in (170, 171):          # tableswitch / lookupswitch
            p += (4 - (p % 4)) % 4    # padding ate multiplo de 4
            default = struct.unpack_from(">i", code, p)[0]
            p += 4
            if op == 170:
                lo, hi = struct.unpack_from(">ii", code, p)
                p += 8 + 4 * (hi - lo + 1)
                linhas.append(f"{inicio:5}: tableswitch {lo}..{hi} "
                              f"default={inicio + default}")
            else:
                n = struct.unpack_from(">i", code, p)[0]
                p += 4 + 8 * n
                linhas.append(f"{inicio:5}: lookupswitch n={n} "
                              f"default={inicio + default}")
            continue

        if op == 196:                 # wide
            alvo = code[p]
            p += 5 if alvo == 132 else 3
            linhas.append(f"{inicio:5}: wide {OPS.get(alvo, ('?', 0))[0]}")
            continue

        nome, tamanho = OPS.get(op, (f"op{op}", 0))
        args = code[p:p + tamanho]
        p += tamanho

        if nome == "ldc":
            texto = f"{nome} {cf.const(args[0])}"
        elif nome in REFERENCIA:
            texto = f"{nome} {cf.const(struct.unpack('>H', args[:2])[0])}"
        elif tamanho == 2 and nome.startswith(("if", "goto", "jsr")):
            texto = f"{nome} -> {inicio + struct.unpack('>h', args)[0]}"
        elif tamanho == 1:
            texto = f"{nome} {args[0]}"
        elif tamanho == 2:
            texto = f"{nome} {struct.unpack('>H', args)[0]}"
        elif tamanho:
            texto = f"{nome} {args.hex()}"
        else:
            texto = nome
        linhas.append(f"{inicio:5}: {texto}")
    return linhas


# ---------------------------------------------------------------------------
# Onde achar a classe
# ---------------------------------------------------------------------------

def carregar(nome: str) -> bytes:
    alvo = Path(nome)
    if alvo.suffix == ".class" and alvo.exists():
        return alvo.read_bytes()

    caminho = nome.replace(".", "/")
    if not caminho.endswith(".class"):
        caminho += ".class"
    jar = paths.game() / "projectzomboid.jar"
    if not jar.exists():
        sys.exit(f"jar do jogo nao encontrado: {jar}")
    with zipfile.ZipFile(jar) as z:
        try:
            return z.read(caminho)
        except KeyError:
            iguais = [n for n in z.namelist()
                      if n.endswith("/" + caminho.rsplit("/", 1)[-1])]
            dica = "\n  ".join(iguais[:10])
            sys.exit(f"{caminho} nao esta no jar."
                     + (f"\nTalvez:\n  {dica}" if iguais else ""))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__.strip())

    cf = ClassFile(carregar(sys.argv[1]))
    filtro = sys.argv[2] if len(sys.argv) > 2 else None

    pai = cf.classe(cf.sup) if cf.sup else "-"
    print(f"class {cf.classe(cf.this)} extends {pai}")

    if filtro == "--fields":
        for acc, nome, desc, _ in cf.fields:
            print(f"  FIELD {nome} {desc} (acc={acc})")
        return

    so_assinatura = filtro in (None, "--methods")
    for acc, nome, desc, attrs in cf.methods:
        if not so_assinatura and filtro not in nome:
            continue
        print(f"\n  METHOD {nome}{desc} (acc={acc})")
        if so_assinatura:
            continue
        for code in attrs.get("Code", []):
            # Code: u2 max_stack, u2 max_locals, u4 code_length, code[]
            tamanho = struct.unpack_from(">I", code, 4)[0]
            for linha in desmontar(cf, code[8:8 + tamanho]):
                print("    " + linha)


if __name__ == "__main__":
    main()
