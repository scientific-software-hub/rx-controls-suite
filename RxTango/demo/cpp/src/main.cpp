#include <tango.h>

#include <iostream>

int main(int argc, char *argv[]) {
    try {
        Tango::Util *util = Tango::Util::init(argc, argv);
        util->server_init(false);
        std::cout << "Ready to accept request" << std::endl;
        util->server_run();
    } catch (const Tango::DevFailed &error) {
        Tango::Except::print_exception(error);
        return 1;
    } catch (const std::exception &error) {
        std::cerr << error.what() << std::endl;
        return 1;
    }

    return 0;
}
