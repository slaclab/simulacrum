from cmd import Cmd
from util_tao import taoCmd

class Prompt(Cmd):
    prompt = '>>'

    def do_exit(self, inp):
        print("Exiting");
        return True

    def default(self, inp):
        taoCmd(inp);

Prompt().cmdloop()


