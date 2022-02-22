struct Requests {
    int key;
    char *url[150]; // Max URL in our case is ~100 chars
    struct Requests *next;
};
