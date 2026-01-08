window.config = {
  routerBasename: "/",
  extensions: [],
  showStudyList: true,
  filterQueryParam: false,
  disableServersCache: false,
  servers: {
    dicomWeb: [
      {
        name: "Orthanc",
        wadoUriRoot: "/orthanc/wado",
        qidoRoot: "/orthanc/dicom-web",
        wadoRoot: "/orthanc/dicom-web",
        qidoSupportsIncludeField: true,
        imageRendering: "wadouri",
        thumbnailRendering: "wadouri",
        enableStudyLazyLoad: true,
        supportsFuzzyMatching: true,
      },
    ],
  },
};
